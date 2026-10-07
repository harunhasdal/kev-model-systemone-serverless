"""Copy the Kev adapter and its base model from the Hugging Face Hub to S3.

list_files resolves both repos to commit shas, lists the files the Kev loader needs and prunes stale keys under the
managed prefixes. copy_file streams one file into S3 with a multipart upload, so nothing is written to local disk.
"""
import json
import os
import urllib.parse
import urllib.request

import boto3
from boto3.s3.transfer import TransferConfig
from botocore.exceptions import ClientError

HUB = "https://huggingface.co"
ALLOWED_SUFFIXES = (".json", ".safetensors", ".pt", ".txt", ".jinja")   # what kev.checkpoint.resolve_run downloads
MODEL_PREFIX = "models"
MB = 1024 * 1024

s3 = boto3.client("s3")


def _request(url):
    return urllib.request.Request(url, headers={"User-Agent": "kev-model-systemone-serverless"})


def _get_json(url):
    """-> (parsed body, url of the next page or None)."""
    with urllib.request.urlopen(_request(url), timeout=30) as resp:
        link = resp.headers.get("Link", "")
        next_url = next((part.split(";")[0].strip(" <>") for part in link.split(",") if 'rel="next"' in part), None)
        return json.load(resp), next_url


def select_files(tree):
    return [e for e in tree if e["type"] == "file" and e["path"].endswith(ALLOWED_SUFFIXES)]


def resolve_sha(repo, revision):
    body, _ = _get_json(f"{HUB}/api/models/{repo}/revision/{urllib.parse.quote(revision, safe='')}")
    return body["sha"]


def list_tree(repo, sha):
    url, tree = f"{HUB}/api/models/{repo}/tree/{sha}?recursive=true", []
    while url:
        page, url = _get_json(url)
        tree += page
    return tree


def prune(bucket, prefix, keep):
    """Delete keys under prefix that the current listing no longer contains."""
    stale = []
    for page in s3.get_paginator("list_objects_v2").paginate(Bucket=bucket, Prefix=prefix):
        stale += [{"Key": o["Key"]} for o in page.get("Contents", []) if o["Key"] not in keep]
    for i in range(0, len(stale), 1000):
        s3.delete_objects(Bucket=bucket, Delete={"Objects": stale[i:i + 1000]})


def list_files(event, _context):
    bucket = os.environ["BUCKET"]
    sources = {
        "adapter": (event.get("adapterRepo") or os.environ["ADAPTER_REPO"], event.get("adapterRevision") or "main"),
        "base": (event.get("baseRepo") or os.environ["BASE_REPO"], event.get("baseRevision") or "main"),
    }
    files, resolved = [], {}
    for name, (repo, revision) in sources.items():
        sha = resolve_sha(repo, revision)
        prefix = f"{MODEL_PREFIX}/{name}/"
        entries = [{"url": f"{HUB}/{repo}/resolve/{sha}/{urllib.parse.quote(e['path'])}", "key": prefix + e["path"], "size": e["size"]}
                   for e in select_files(list_tree(repo, sha))]
        prune(bucket, prefix, {e["key"] for e in entries})
        files += entries
        resolved[name] = {"repo": repo, "sha": sha, "files": len(entries)}
    return {"files": files, "sources": resolved}


def _size_of(bucket, key):
    try:
        return s3.head_object(Bucket=bucket, Key=key)["ContentLength"]
    except ClientError as e:
        if e.response["Error"]["Code"] in ("404", "NoSuchKey", "NotFound"):
            return None
        raise


def copy_file(event, _context):
    bucket, key, size = os.environ["BUCKET"], event["key"], int(event["size"])
    if _size_of(bucket, key) == size:
        return {"key": key, "skipped": True}
    config = TransferConfig(multipart_threshold=64 * MB, multipart_chunksize=64 * MB, use_threads=False)
    with urllib.request.urlopen(_request(event["url"]), timeout=60) as resp:
        s3.upload_fileobj(resp, bucket, key, Config=config)
    copied = _size_of(bucket, key)
    if copied != size:
        raise RuntimeError(f"{key}: expected {size} bytes, S3 has {copied}")
    return {"key": key, "skipped": False, "size": size}

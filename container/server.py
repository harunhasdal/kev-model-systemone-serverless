"""Lambda entry point: fetch Kev from S3, load it on CPU and serve kev.serve's FastAPI app on $AWS_LWA_PORT.

The port opens only after the model is loaded, so Lambda Web Adapter (AWS_LWA_ASYNC_INIT) holds the first request
until the server is ready. MODEL_DIR skips S3 and uses a local directory with adapter/ and base/ (local testing).
"""
import os
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import torch

MAX_STATE_TOKENS = int(os.environ.get("MAX_STATE_TOKENS", "8192"))
PORT = int(os.environ.get("AWS_LWA_PORT", "8080"))
DEST = Path("/tmp/model")


def download(bucket: str, prefix: str, dest: Path) -> Path:
    import boto3
    s3 = boto3.client("s3")
    keys = [o["Key"] for page in s3.get_paginator("list_objects_v2").paginate(Bucket=bucket, Prefix=prefix)
            for o in page.get("Contents", [])]
    if not keys:
        raise RuntimeError(f"no objects under s3://{bucket}/{prefix}; run the ingest state machine first")

    def fetch(key: str):
        target = dest / key[len(prefix):]
        target.parent.mkdir(parents=True, exist_ok=True)
        s3.download_file(bucket, key, str(target))

    with ThreadPoolExecutor(4) as pool:
        list(pool.map(fetch, keys))
    return dest


def main():
    started = time.time()
    if local := os.environ.get("MODEL_DIR"):
        adapter, base = Path(local) / "adapter", Path(local) / "base"
    else:
        bucket = os.environ["MODEL_BUCKET"]
        adapter = download(bucket, "models/adapter/", DEST / "adapter")
        base = download(bucket, "models/base/", DEST / "base")
    print(f"model files ready in {time.time() - started:.1f}s", flush=True)

    # Serving limit: kev.model.admit reads these at call time and kev.serve imports them at import time.
    import kev.model as km
    km.SERVE_MAX_STATE = km.SERVE_MAX_BRANCH = MAX_STATE_TOKENS

    from kev import serve
    from kev.checkpoint import Checkpoint, LoadOptions, read_meta, write_meta

    # head.pt names the base by Hub id and revision; point it at the copy fetched from S3 (the Hub is not reachable).
    meta = read_meta(adapter)
    meta.base, meta.base_revision = str(base), None
    write_meta(adapter, meta)

    torch.set_num_threads(int(os.environ.get("OMP_NUM_THREADS", "6")))
    checkpoint = Checkpoint(str(adapter))
    tok, model = checkpoint.load("cpu", LoadOptions.from_env())
    serve.app.state.server = serve.Server(checkpoint, tok, model, "cpu")
    print(f"model loaded, {time.time() - started:.1f}s since start; serving on :{PORT}", flush=True)

    import uvicorn
    uvicorn.run(serve.app, host="0.0.0.0", port=PORT)


if __name__ == "__main__":
    main()

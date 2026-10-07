"""Lambda entry point: load the Kev adapter and base model baked into the image on CPU and serve kev.serve's app.

The port opens only after the model is loaded, so Lambda Web Adapter (AWS_LWA_ASYNC_INIT) holds the first request
until the server is ready. MODEL_DIR holds adapter/ and base/ (the image has them at /opt/model); they are staged
to /tmp before loading.
"""
import os
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import torch

IMAGE_DIR = Path(os.environ.get("MODEL_DIR", "/opt/model"))
MODEL_DIR = Path("/tmp/model")
CHUNK = 64 * 1024 * 1024
MAX_STATE_TOKENS = int(os.environ.get("MAX_STATE_TOKENS", "8192"))
PORT = int(os.environ.get("AWS_LWA_PORT", "8080"))


def stage(src: Path, dst: Path, workers: int = 8) -> None:
    """Copy the model from the image to /tmp with large parallel reads.

    Lambda loads container images lazily. Loading the safetensors straight from the image memory-maps the file, so each
    page fault is a small read over the network and the load did not finish in 120 s. Sequential 64 MB reads are fast.
    """
    jobs = []
    for path in sorted(p for p in src.rglob("*") if p.is_file()):
        target = dst / path.relative_to(src)
        target.parent.mkdir(parents=True, exist_ok=True)
        size = path.stat().st_size
        with open(target, "wb") as f:
            f.truncate(size)
        jobs += [(path, target, offset, min(CHUNK, size - offset)) for offset in range(0, size, CHUNK)]

    def copy(job):
        path, target, offset, length = job
        with open(path, "rb") as r, open(target, "r+b") as w:
            r.seek(offset)
            w.seek(offset)
            w.write(r.read(length))

    with ThreadPoolExecutor(workers) as pool:
        list(pool.map(copy, jobs))


def main():
    started = time.time()
    stage(IMAGE_DIR, MODEL_DIR)
    print(f"model staged to {MODEL_DIR} in {time.time() - started:.1f}s", flush=True)

    # Serving limit: kev.model.admit reads these at call time and kev.serve imports them at import time.
    import kev.model as km
    km.SERVE_MAX_STATE = km.SERVE_MAX_BRANCH = MAX_STATE_TOKENS

    from kev import serve
    from kev.checkpoint import Checkpoint, LoadOptions, read_meta, write_meta

    # head.pt names the base by Hub id and revision; point it at the staged copy (the Hub is not reachable).
    adapter = MODEL_DIR / "adapter"
    meta = read_meta(adapter)
    meta.base, meta.base_revision = str(MODEL_DIR / "base"), None
    write_meta(adapter, meta)

    torch.set_num_threads(int(os.environ.get("OMP_NUM_THREADS", "6")))
    checkpoint = Checkpoint(str(adapter))
    tok, model = checkpoint.load("cpu", LoadOptions.from_env())
    serve.app.state.server = serve.Server(checkpoint, tok, model, "cpu")
    print(f"model loaded in {time.time() - started:.1f}s; serving on :{PORT}", flush=True)

    import uvicorn
    uvicorn.run(serve.app, host="0.0.0.0", port=PORT)


if __name__ == "__main__":
    main()

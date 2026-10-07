"""Lambda entry point: load the Kev adapter and base model baked into the image on CPU and serve kev.serve's app.

The port opens only after the model is loaded, so Lambda Web Adapter (AWS_LWA_ASYNC_INIT) holds the first request
until the server is ready. MODEL_DIR holds adapter/ and base/ (the image has them at /opt/model).
"""
import os
import shutil
import time
from pathlib import Path

import torch

MODEL_DIR = Path(os.environ.get("MODEL_DIR", "/opt/model"))
MAX_STATE_TOKENS = int(os.environ.get("MAX_STATE_TOKENS", "8192"))
PORT = int(os.environ.get("AWS_LWA_PORT", "8080"))
WORK_DIR = Path("/tmp/adapter")


def main():
    started = time.time()

    # Serving limit: kev.model.admit reads these at call time and kev.serve imports them at import time.
    import kev.model as km
    km.SERVE_MAX_STATE = km.SERVE_MAX_BRANCH = MAX_STATE_TOKENS

    from kev import serve
    from kev.checkpoint import Checkpoint, LoadOptions, read_meta, write_meta

    # head.pt names the base by Hub id and revision; point it at the baked copy (the Hub is not reachable). The image
    # is read-only, so the small adapter directory is copied to /tmp first.
    shutil.copytree(MODEL_DIR / "adapter", WORK_DIR, dirs_exist_ok=True)
    meta = read_meta(WORK_DIR)
    meta.base, meta.base_revision = str(MODEL_DIR / "base"), None
    write_meta(WORK_DIR, meta)

    torch.set_num_threads(int(os.environ.get("OMP_NUM_THREADS", "6")))
    checkpoint = Checkpoint(str(WORK_DIR))
    tok, model = checkpoint.load("cpu", LoadOptions.from_env())
    serve.app.state.server = serve.Server(checkpoint, tok, model, "cpu")
    print(f"model loaded in {time.time() - started:.1f}s; serving on :{PORT}", flush=True)

    import uvicorn
    uvicorn.run(serve.app, host="0.0.0.0", port=PORT)


if __name__ == "__main__":
    main()

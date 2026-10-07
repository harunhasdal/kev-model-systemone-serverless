import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[2] / "lambdas" / "ingest"))

import ingest  # noqa: E402


def test_select_files_keeps_loader_files_only():
    tree = [
        {"type": "file", "path": "config.json", "size": 1},
        {"type": "file", "path": "model.safetensors-00001-of-00001.safetensors", "size": 2},
        {"type": "file", "path": "head.pt", "size": 3},
        {"type": "file", "path": "README.md", "size": 4},
        {"type": "file", "path": "train.log", "size": 5},
        {"type": "directory", "path": "assets.json", "size": 0},
    ]
    assert [e["path"] for e in ingest.select_files(tree)] == [
        "config.json", "model.safetensors-00001-of-00001.safetensors", "head.pt",
    ]

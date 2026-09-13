"""Downloads the CLIP checkpoint used by uploaded-media analysis into ./models/hf.

Weights stay out of git and out of the Docker image: `models/` is bind-mounted,
so the model is fetched once per machine and reused by every container run.
Re-running is cheap -- an existing snapshot is reused from the local cache.

Offline demos: run this once while the network is available, then export
HF_HUB_OFFLINE=1 so no request leaves the machine.
"""
from __future__ import annotations

import sys
from pathlib import Path


def main() -> int:
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

    from backend.config import settings

    cache_dir: Path = settings.MEDIA_CACHE_DIR
    cache_dir.mkdir(parents=True, exist_ok=True)

    print(f"Model:     {settings.CLIP_MODEL_NAME}")
    print(f"Cache dir: {cache_dir}")

    try:
        from transformers import CLIPModel, CLIPProcessor
    except ImportError:
        print("ERROR: transformers is not installed. Run: uv sync")
        return 2

    try:
        CLIPModel.from_pretrained(settings.CLIP_MODEL_NAME, cache_dir=str(cache_dir))
        CLIPProcessor.from_pretrained(settings.CLIP_MODEL_NAME, cache_dir=str(cache_dir))
    except Exception as exc:
        print(f"ERROR: could not download the model: {exc}")
        return 1

    total = sum(path.stat().st_size for path in cache_dir.rglob("*") if path.is_file())
    print(f"Ready. Local size: {total / (1024 * 1024):.1f} MB")
    print("For an offline run set HF_HUB_OFFLINE=1 before starting the API.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

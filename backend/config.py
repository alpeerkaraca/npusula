"""Configuration and environment settings for NPusula.

Every value is read from the process environment, after the repository's
`.env` file has been loaded into it (see `backend/env_loader.py`); a variable
that the environment already defines takes precedence over `.env`. The keys
this module reads are documented in `.env.example`.
"""
import os
from pathlib import Path
import socket
import urllib.request

from backend.env_loader import load_project_env

load_project_env()


def find_qdrant_host() -> str:
    """Discovers accessible Qdrant host (localhost, WSL IP, or env var)."""
    env_host = os.getenv("QDRANT_HOST")
    if env_host:
        return env_host

    # Try localhost first
    for candidate in ["127.0.0.1", "localhost", "172.17.78.187"]:
        try:
            with urllib.request.urlopen(f"http://{candidate}:6333/healthz", timeout=1.0) as resp:
                if resp.status == 200:
                    return candidate
        except Exception:
            continue

    return "127.0.0.1"


class Settings:
    BASE_DIR: Path = Path(__file__).resolve().parent.parent
    DATA_DIR: Path = BASE_DIR / "data"
    PROCESSED_DATA_PATH: Path = DATA_DIR / "processed" / "posts.parquet"
    ARTIFACTS_DIR: Path = BASE_DIR / "artifacts"
    DEMO_ACCOUNTS_PATH: Path = ARTIFACTS_DIR / "demo_accounts.json"

    # --- Runtime state -------------------------------------------------------
    # Interests and saved content written while the app runs. `data/` is
    # gitignored while `artifacts/` is tracked (see .gitignore), so runtime
    # state lives here and never shows up as repository dirt or provenance.
    # Kept deliberately separate from DEMO_ACCOUNTS_PATH: the curated demo
    # roster must stay untouched, so /api/demo-users keeps answering [].
    STATE_DIR: Path = Path(os.getenv("NPUSULA_STATE_DIR", str(DATA_DIR / "state")))
    DECLARED_TOPICS_PATH: Path = STATE_DIR / "declared_topics.json"
    SAVED_CONTENT_PATH: Path = STATE_DIR / "saved_content.json"

    # --- Layer A / Layer B artifacts (plan §4, §5) ---------------------------
    # The pre-rework artifacts (metrics.json, lgbm_popularity.txt,
    # tuning_results.json, pytorch_popularity_gpu.pt) live in artifacts/legacy/
    # and are never loaded by the runtime.
    MODEL_PATH: Path = ARTIFACTS_DIR / "base_potential_lgbm.txt"
    METRICS_PATH: Path = ARTIFACTS_DIR / "base_potential_metrics.json"
    TIME_LIFT_PATH: Path = ARTIFACTS_DIR / "time_lift_table.json"
    TUNING_PATH: Path = ARTIFACTS_DIR / "tuning_results.json"
    FINAL_EVALUATION_PATH: Path = ARTIFACTS_DIR / "final_evaluation.json"
    LEGACY_ARTIFACTS_DIR: Path = ARTIFACTS_DIR / "legacy"

    GEMMA_MODEL_NAME: str = os.getenv("GEMMA_MODEL_NAME", "gemma4:e4b")
    GEMMA_API_URL: str = os.getenv("GEMMA_API_URL", "http://127.0.0.1:11434")

    QDRANT_HOST: str = find_qdrant_host()
    QDRANT_PORT: int = int(os.getenv("QDRANT_PORT", "6333"))
    QDRANT_COLLECTION: str = "successful_posts"
    VECTOR_DIM: int = 512

    # --- Uploaded media analysis (photo/video -> CLIP zero-shot) ---
    # Weights live outside the image/artifacts: `models/` is bind-mounted, so a
    # checkpoint is never baked into the Docker image or committed to git.
    MODELS_DIR: Path = BASE_DIR / "models"
    MEDIA_CACHE_DIR: Path = Path(os.getenv("MEDIA_CACHE_DIR", str(MODELS_DIR / "hf")))
    CLIP_MODEL_NAME: str = os.getenv("CLIP_MODEL_NAME", "openai/clip-vit-base-patch32")
    # "cpu" (default), "auto" (try DeviceManager first, then CPU), "cuda", "directml".
    # Defaults to CPU because DirectML cannot run this model (it raises
    # "Cannot set version_counter for inference tensor"), and CPU inference is
    # ~60 ms per image, which is negligible next to the LLM call.
    MEDIA_DEVICE: str = os.getenv("MEDIA_DEVICE", "cpu")
    MAX_IMAGE_MB: float = float(os.getenv("MAX_IMAGE_MB", "10"))
    MAX_VIDEO_MB: float = float(os.getenv("MAX_VIDEO_MB", "50"))
    MAX_VIDEO_SECONDS: float = float(os.getenv("MAX_VIDEO_SECONDS", "60"))
    VIDEO_FRAME_COUNT: int = int(os.getenv("VIDEO_FRAME_COUNT", "8"))
    MEDIA_ANALYSIS_TTL_SECONDS: int = int(os.getenv("MEDIA_ANALYSIS_TTL_SECONDS", "1800"))
    MEDIA_TOP_TAGS: int = int(os.getenv("MEDIA_TOP_TAGS", "3"))
    # Confidence floors are calibrated against the hand-labelled fixture set in
    # tests/fixtures/media (see tests/test_media_analysis.py). They are CLIP
    # softmax values and must not be confused with the TF-IDF cosine thresholds
    # used by ProfileService.
    MEDIA_MIN_PROB: float = float(os.getenv("MEDIA_MIN_PROB", "0.35"))
    MEDIA_MIN_MARGIN: float = float(os.getenv("MEDIA_MIN_MARGIN", "0.10"))
    # Tags are scored against a much larger label bank than categories, so their
    # softmax mass is spread thinner; they get their own floor.
    MEDIA_TAG_MIN_PROB: float = float(os.getenv("MEDIA_TAG_MIN_PROB", "0.10"))


settings = Settings()

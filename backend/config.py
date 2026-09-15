"""Configuration and environment settings for NPusula.

Every value is read from the process environment, after the repository's
`.env` file has been loaded into it (see `backend/env_loader.py`); a variable
that the environment already defines takes precedence over `.env`. The keys
this module reads are documented in `.env.example`.
"""
import json
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


def find_base_potential_mean() -> float | None:
    """Mean popularity score of the data Layer A was trained on.

    Read from the training artifact so the advisor can say where a score sits
    relative to the population instead of showing the reader a bare number.
    Returns None when the artifact is missing or malformed; callers then omit
    the comparison rather than inventing a baseline.
    """
    metrics_path = Path(__file__).resolve().parent.parent / "artifacts" / "base_potential_metrics.json"
    try:
        payload = json.loads(metrics_path.read_text(encoding="utf-8"))
    except Exception:
        return None
    value = payload.get("global_train_mean")
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


class Settings:
    BASE_DIR: Path = Path(__file__).resolve().parent.parent
    DATA_DIR: Path = BASE_DIR / "data"
    PROCESSED_DATA_PATH: Path = DATA_DIR / "processed" / "posts.parquet"
    ARTIFACTS_DIR: Path = BASE_DIR / "artifacts"
    DEMO_ACCOUNTS_PATH: Path = ARTIFACTS_DIR / "demo_accounts.json"
    # Selectable accounts for the frontend picker. Separate file from the demo
    # roster on purpose: that one must stay absent so /api/demo-users keeps
    # answering [] (locked by tests/test_api_endpoints.py).
    SAMPLE_USERS_PATH: Path = ARTIFACTS_DIR / "sample_users.json"

    # --- Runtime state -------------------------------------------------------
    # Interests and saved content written while the app runs. `data/` is
    # gitignored while `artifacts/` is tracked (see .gitignore), so runtime
    # state lives here and never shows up as repository dirt or provenance.
    # Kept deliberately separate from DEMO_ACCOUNTS_PATH: the curated demo
    # roster must stay untouched, so /api/demo-users keeps answering [].
    STATE_DIR: Path = Path(os.getenv("NPUSULA_STATE_DIR", str(DATA_DIR / "state")))
    DECLARED_TOPICS_PATH: Path = STATE_DIR / "declared_topics.json"
    SAVED_CONTENT_PATH: Path = STATE_DIR / "saved_content.json"
    SQLITE_DB_PATH: Path = Path(
        os.getenv("NPUSULA_SQLITE_PATH", os.getenv("NPUSULA_DB_PATH", str(STATE_DIR / "npusula.db")))
    )

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

    # Population mean of the training target, so the advisor prompt can place a
    # base_potential score relative to the data. None = artifact unreadable.
    BASE_POTENTIAL_MEAN: float | None = find_base_potential_mean()

    # --- LLM Service Settings (Generic) ------------------------------------
    LLM_MODEL_NAME: str = os.getenv("LLM_MODEL_NAME", os.getenv("GEMMA_MODEL_NAME", "qwen3-vl:4b-instruct"))
    LLM_API_URL: str = os.getenv("LLM_API_URL", os.getenv("GEMMA_API_URL", "http://127.0.0.1:11434"))
    # Reasoning / thinking mode toggle. With thinking on, models spend the
    # generation budget on internal reasoning tokens; set false for direct responses.
    LLM_THINK: bool = os.getenv("LLM_THINK", os.getenv("GEMMA_THINK", "false")).strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }
    # Generation cap to bound latency and guarantee predictable timeouts.
    LLM_MAX_TOKENS: int = int(os.getenv("LLM_MAX_TOKENS", os.getenv("GEMMA_MAX_TOKENS", "512")))
    # Topic judge needs only a single label.
    LLM_JUDGE_MAX_TOKENS: int = int(os.getenv("LLM_JUDGE_MAX_TOKENS", os.getenv("GEMMA_JUDGE_MAX_TOKENS", "32")))
    # Moderation guardrail returns a compact JSON verdict.
    LLM_MODERATION_MAX_TOKENS: int = int(
        os.getenv("LLM_MODERATION_MAX_TOKENS", os.getenv("GEMMA_MODERATION_MAX_TOKENS", "128"))
    )
    LLM_TIMEOUT_SECONDS: float = float(os.getenv("LLM_TIMEOUT_SECONDS", os.getenv("GEMMA_TIMEOUT_SECONDS", "30.0")))
    LLM_RETRY_COUNT: int = int(os.getenv("LLM_RETRY_COUNT", os.getenv("GEMMA_RETRY_COUNT", "2")))
    LLM_VISION_TIMEOUT_SECONDS: float = float(
        os.getenv("LLM_VISION_TIMEOUT_SECONDS", os.getenv("GEMMA_VISION_TIMEOUT_SECONDS", "15.0"))
    )

    # Backward-compatibility aliases for legacy code and existing environments
    GEMMA_MODEL_NAME: str = LLM_MODEL_NAME
    GEMMA_API_URL: str = LLM_API_URL
    GEMMA_THINK: bool = LLM_THINK
    GEMMA_MAX_TOKENS: int = LLM_MAX_TOKENS
    GEMMA_JUDGE_MAX_TOKENS: int = LLM_JUDGE_MAX_TOKENS
    GEMMA_MODERATION_MAX_TOKENS: int = LLM_MODERATION_MAX_TOKENS
    GEMMA_TIMEOUT_SECONDS: float = LLM_TIMEOUT_SECONDS
    GEMMA_RETRY_COUNT: int = LLM_RETRY_COUNT
    GEMMA_VISION_TIMEOUT_SECONDS: float = LLM_VISION_TIMEOUT_SECONDS

    QDRANT_HOST: str = find_qdrant_host()
    QDRANT_PORT: int = int(os.getenv("QDRANT_PORT", "6333"))
    QDRANT_COLLECTION: str = "successful_posts"
    VECTOR_DIM: int = 512

    # --- Uploaded media analysis (llm | clip) ---
    MEDIA_ANALYZER_BACKEND: str = os.getenv("MEDIA_ANALYZER_BACKEND", "llm").strip().lower()
    # Weights live outside the image/artifacts: `models/` is bind-mounted, so a
    # checkpoint is never baked into the Docker image or committed to git.
    MODELS_DIR: Path = BASE_DIR / "models"
    MEDIA_CACHE_DIR: Path = Path(os.getenv("MEDIA_CACHE_DIR", str(MODELS_DIR / "hf")))
    VISION_MODEL_NAME: str = os.getenv("VISION_MODEL_NAME", os.getenv("CLIP_MODEL_NAME", "openai/clip-vit-base-patch32"))
    CLIP_MODEL_NAME: str = VISION_MODEL_NAME
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
    MEDIA_TAG_MIN_PROB: float = float(os.getenv("MEDIA_TAG_MIN_PROB", "0.10"))

    # --- Nextcloud WebDAV (artifact sync) -----------------------------------
    WEBDAV_URL: str = os.getenv("WEBDAV_URL", "https://cloud.alpeerkaraca.me/remote.php/dav/files/alpeerkaraca/HTWH101/")
    WEBDAV_USER: str = os.getenv("WEBDAV_USER", "alpeerkaraca")
    WEBDAV_PASSWORD: str = os.getenv("WEBDAV_PASSWORD", "")
    AUTO_SYNC_ARTIFACTS_ON_STARTUP: bool = os.getenv(
        "AUTO_SYNC_ARTIFACTS_ON_STARTUP", "true"
    ).strip().lower() in {"1", "true", "yes", "on"}
    ARTIFACT_SYNC_TIMEOUT_SECONDS: float = float(os.getenv("ARTIFACT_SYNC_TIMEOUT_SECONDS", "15.0"))


settings = Settings()

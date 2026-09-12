"""Configuration and environment settings for EnPusula."""
import os
from pathlib import Path
import socket
import urllib.request


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
    MODEL_PATH: Path = ARTIFACTS_DIR / "lgbm_popularity.txt"
    METRICS_PATH: Path = ARTIFACTS_DIR / "metrics.json"

    GEMMA_MODEL_NAME: str = os.getenv("GEMMA_MODEL_NAME", "google/gemma-4-E4B-it")
    GEMMA_API_URL: str = os.getenv("GEMMA_API_URL", "http://127.0.0.1:11434")

    QDRANT_HOST: str = find_qdrant_host()
    QDRANT_PORT: int = int(os.getenv("QDRANT_PORT", "6333"))
    QDRANT_COLLECTION: str = "successful_posts"
    VECTOR_DIM: int = 512


settings = Settings()

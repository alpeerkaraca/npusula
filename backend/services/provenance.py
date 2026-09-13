"""Reproducibility metadata attached to every pipeline artifact (plan §0.1).

Every training/pipeline output carries the dataset hash, the git commit, the
training time, the row count and the split boundaries. Without those, a metrics
file is an unfalsifiable claim; with them it can be re-derived and audited.
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess

from backend.config import settings


def git_commit_sha(default: str = "unknown") -> str:
    """Returns the current git commit SHA, or ``default`` outside a repository."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=settings.BASE_DIR,
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        sha = result.stdout.strip()
        return sha if sha else default
    except (OSError, subprocess.SubprocessError):
        return default


def git_is_dirty() -> bool:
    """True when the working tree has uncommitted changes."""
    try:
        result = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=settings.BASE_DIR,
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        return bool(result.stdout.strip())
    except (OSError, subprocess.SubprocessError):
        return False


def file_sha256(path: Path, chunk_size: int = 1 << 20) -> str:
    """Streams a file through SHA-256 (constant memory)."""
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(chunk_size), b""):
            digest.update(chunk)
    return digest.hexdigest()


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def write_json_with_provenance(path: Path, payload: dict, provenance: dict) -> None:
    """Writes ``payload`` plus a ``provenance`` block to ``path``."""
    path.parent.mkdir(parents=True, exist_ok=True)
    document = {**payload, "provenance": provenance}
    path.write_text(json.dumps(document, indent=2, ensure_ascii=False, default=str), encoding="utf-8")


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))

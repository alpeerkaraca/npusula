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


CODE_PATHS = ("backend", "scripts", "tests")


def git_is_dirty() -> bool:
    """True when the working tree has any uncommitted change."""
    return bool(_git_status_lines())


def git_code_is_dirty() -> bool:
    """True when tracked *code* differs from HEAD.

    A pipeline run necessarily rewrites the artifacts it produces, so a plain
    "worktree is dirty" flag would be true for every step after the first and
    would tell an auditor nothing. This flag answers the question that matters:
    was the code that produced this artifact exactly the committed code?
    """
    lines = _git_status_lines(*CODE_PATHS)
    return bool(lines)


def _git_status_lines(*paths: str) -> list[str]:
    command = ["git", "status", "--porcelain", *paths]
    try:
        result = subprocess.run(
            command,
            cwd=settings.BASE_DIR,
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return []
    return [line for line in result.stdout.splitlines() if line.strip()]


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

"""Runtime artifact freshness checker and synchronization with Nextcloud WebDAV.

Runs on backend startup (lifespan) to ensure model weights, tables, datasets,
and the SQLite database match the remote Nextcloud repository.
"""
from __future__ import annotations

import base64
from datetime import datetime, timezone
import email.utils
import logging
import os
from pathlib import Path
import time
from typing import Any
import urllib.error
import urllib.request

from backend.config import settings

logger = logging.getLogger("backend.services.artifact_sync")

REMOTE_DIR_NAME = "npusula_artifacts"

# Manifest of artifacts kept in sync: (relative_path, is_required)
SYNC_MANIFEST: list[tuple[str, bool]] = [
    ("artifacts/base_potential_lgbm.txt", True),
    ("artifacts/base_potential_metrics.json", True),
    ("artifacts/time_lift_table.json", True),
    ("artifacts/text_svd_model.joblib", True),
    ("artifacts/qdrant_context_engine.joblib", True),
    ("artifacts/guardrail_classifier.joblib", True),
    ("artifacts/guardrail_metrics.json", False),
    ("artifacts/final_evaluation.json", False),
    ("data/processed/posts.parquet", True),
    ("data/state/npusula.db", False),
]


def _build_auth_headers(user: str, password: str) -> dict[str, str]:
    token = base64.b64encode(f"{user}:{password}".encode("utf-8")).decode("ascii")
    return {"Authorization": f"Basic {token}"}


def _remote_dir_url(base_url: str) -> str:
    cleaned = base_url if base_url.endswith("/") else f"{base_url}/"
    return f"{cleaned}{REMOTE_DIR_NAME}/"


def query_remote_metadata(url: str, headers: dict[str, str], timeout: float = 10.0) -> dict[str, Any] | None:
    """Sends a HEAD request to extract Content-Length, Last-Modified, and ETag."""
    req = urllib.request.Request(url, method="HEAD")
    for k, v in headers.items():
        req.add_header(k, v)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            headers_dict = dict(resp.headers)
            content_length = int(headers_dict.get("Content-Length") or 0)
            last_modified = headers_dict.get("Last-Modified")
            etag = headers_dict.get("ETag")
            remote_mtime = None
            if last_modified:
                try:
                    dt = email.utils.parsedate_to_datetime(last_modified)
                    remote_mtime = dt.timestamp()
                except Exception:
                    pass
            return {
                "size": content_length,
                "last_modified": last_modified,
                "remote_mtime": remote_mtime,
                "etag": etag,
            }
    except Exception as exc:
        logger.debug("HEAD query failed for %s: %s", url, exc)
        return None


def download_artifact(
    url: str,
    target: Path,
    headers: dict[str, str],
    expected_size: int,
    timeout: float = 60.0,
) -> bool:
    """Downloads remote file into a temporary file and atomically replaces target."""
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = target.with_name(f"{target.name}.tmp")

    # If updating an existing SQLite database, preserve a backup
    if target.exists() and target.suffix == ".db":
        backup_path = target.with_name(f"{target.name}.bak")
        try:
            target.replace(backup_path)
            logger.info("backed up existing database to %s before sync", backup_path)
        except Exception as exc:
            logger.warning("could not create database backup: %s", exc)

    req = urllib.request.Request(url)
    for k, v in headers.items():
        req.add_header(k, v)

    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp, open(tmp_path, "wb") as out_file:
            while True:
                chunk = resp.read(1024 * 256)
                if not chunk:
                    break
                out_file.write(chunk)

        downloaded_size = tmp_path.stat().st_size
        if expected_size > 0 and downloaded_size != expected_size:
            logger.warning(
                "downloaded size mismatch for %s: %d != %d", target.name, downloaded_size, expected_size
            )
            if tmp_path.exists():
                tmp_path.unlink()
            return False

        os.replace(tmp_path, target)
        logger.info("successfully updated %s (%d bytes)", target.name, downloaded_size)
        return True
    except Exception as exc:
        logger.warning("failed downloading %s from %s: %s", target.name, url, exc)
        if tmp_path.exists():
            try:
                tmp_path.unlink()
            except Exception:
                pass
        return False


def sync_artifacts_if_outdated(
    dest_root: Path | None = None,
    timeout: float | None = None,
) -> dict[str, Any]:
    """Queries Nextcloud for all artifacts and updates any outdated or missing files."""
    user = settings.WEBDAV_USER
    pwd = settings.WEBDAV_PASSWORD
    base_url = settings.WEBDAV_URL
    timeout_sec = timeout or settings.ARTIFACT_SYNC_TIMEOUT_SECONDS

    if not pwd:
        logger.info("Nextcloud WEBDAV_PASSWORD is not set; skipping runtime artifact sync")
        return {"status": "skipped", "reason": "no_credentials"}

    root = dest_root or settings.BASE_DIR
    dir_url = _remote_dir_url(base_url)
    headers = _build_auth_headers(user, pwd)

    summary: dict[str, Any] = {
        "status": "ok",
        "checked": 0,
        "updated": [],
        "up_to_date": [],
        "missing_remote": [],
        "errors": [],
    }

    logger.info("checking artifact freshness with Nextcloud at %s", dir_url)

    for rel, required in SYNC_MANIFEST:
        target = root / rel
        remote_url = dir_url + Path(rel).name
        summary["checked"] += 1

        try:
            meta = query_remote_metadata(remote_url, headers, timeout=min(timeout_sec, 10.0))
            if meta is None:
                if required:
                    summary["missing_remote"].append(rel)
                    logger.warning("required artifact missing on Nextcloud: %s", rel)
                continue

            remote_size = meta["size"]
            remote_mtime = meta["remote_mtime"]

            outdated = False
            reason = ""

            if not target.exists():
                outdated = True
                reason = "missing_locally"
            elif target.stat().st_size != remote_size:
                outdated = True
                reason = f"size_difference (local={target.stat().st_size}, remote={remote_size})"
            elif remote_mtime and (remote_mtime > target.stat().st_mtime + 2.0):
                outdated = True
                reason = "remote_newer"

            if outdated:
                logger.info("artifact %s is outdated (%s); updating from Nextcloud...", rel, reason)
                success = download_artifact(
                    url=remote_url,
                    target=target,
                    headers=headers,
                    expected_size=remote_size,
                    timeout=max(timeout_sec * 2.0, 30.0),
                )
                if success:
                    summary["updated"].append({"path": rel, "reason": reason})
                else:
                    summary["errors"].append({"path": rel, "error": "download_failed"})
            else:
                summary["up_to_date"].append(rel)

        except Exception as exc:
            logger.warning("error checking artifact %s: %s", rel, exc)
            summary["errors"].append({"path": rel, "error": str(exc)})

    logger.info(
        "Nextcloud artifact sync finished: updated=%d, up_to_date=%d, errors=%d",
        len(summary["updated"]),
        len(summary["up_to_date"]),
        len(summary["errors"]),
    )
    return summary

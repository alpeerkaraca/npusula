"""Syncs trained model artifacts with the team Nextcloud over WebDAV.

Teammates fetch the prepared weights instead of retraining from scratch:

    python scripts/sync_artifacts.py download    # resumable, skips up-to-date files
    python scripts/sync_artifacts.py upload      # maintainers publish current weights

Credentials come from WEBDAV_URL, WEBDAV_USER and WEBDAV_PASSWORD - the same
`.env`/environment resolution (backend/env_loader.py) every other entry point
uses, with the environment taking precedence. Files are stored under the
WEBDAV_URL folder in an "npusula_artifacts" subdirectory.
"""
from __future__ import annotations

import argparse
import base64
import os
from pathlib import Path
import time
import urllib.error
import urllib.request

from backend.env_loader import load_project_env

REMOTE_DIR_NAME = "npusula_artifacts"
DEFAULT_BASE_URL = "https://cloud.alpeerkaraca.me/remote.php/dav/files/alpeerkaraca/HTWH101/"
WEBDAV_KEYS = ("WEBDAV_URL", "WEBDAV_USER", "WEBDAV_PASSWORD")

# (path relative to the repo root, required for serving)
MANIFEST: list[tuple[str, bool]] = [
    # Layer A (base potential) + Layer B (time-lift table): both are required at
    # runtime, and the metrics report carries the provenance of both.
    ("artifacts/base_potential_lgbm.txt", True),
    ("artifacts/base_potential_metrics.json", True),
    ("artifacts/time_lift_table.json", True),
    ("artifacts/text_svd_model.joblib", True),
    ("artifacts/qdrant_context_engine.joblib", True),
    ("artifacts/guardrail_classifier.joblib", True),
    ("artifacts/guardrail_metrics.json", False),
    # The locked final evaluation is not needed to serve, but it is what the
    # README quotes, so it travels with the weights.
    ("artifacts/final_evaluation.json", False),
    # Enables rebuilding the Qdrant index without the 458 MB raw dataset.
    ("data/processed/posts.parquet", True),
    # SQLite state database (user declared topics, drift decisions, plans & drafts)
    ("data/state/npusula.db", False),
]


def load_env() -> dict[str, str]:
    """WebDAV settings: process environment first, then the repo `.env`."""
    load_project_env()
    return {key: os.environ[key] for key in WEBDAV_KEYS if os.environ.get(key)}


def remote_dir_url(env: dict[str, str]) -> str:
    base = env.get("WEBDAV_URL", DEFAULT_BASE_URL)
    if not base.endswith("/"):
        base += "/"
    return base + REMOTE_DIR_NAME + "/"


def auth_headers(env: dict[str, str]) -> dict[str, str]:
    user = env.get("WEBDAV_USER", "alpeerkaraca")
    pwd = env.get("WEBDAV_PASSWORD", "")
    token = base64.b64encode(f"{user}:{pwd}".encode()).decode()
    return {"Authorization": f"Basic {token}"}


def remote_size(url: str, headers: dict[str, str]) -> int | None:
    req = urllib.request.Request(url, method="HEAD")
    for key, value in headers.items():
        req.add_header(key, value)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return int(resp.headers.get("Content-Length", 0))
    except Exception:
        return None


def ensure_remote_dir(dir_url: str, headers: dict[str, str]) -> None:
    req = urllib.request.Request(dir_url.rstrip("/"), method="MKCOL")
    for key, value in headers.items():
        req.add_header(key, value)
    try:
        urllib.request.urlopen(req, timeout=30)
        print(f"created remote folder: {dir_url}")
    except urllib.error.HTTPError as e:
        if e.code not in (405, 301):  # already exists / already redirected
            raise


def upload(env: dict[str, str], force: bool = False) -> None:
    dir_url = remote_dir_url(env)
    headers = auth_headers(env)
    ensure_remote_dir(dir_url, headers)

    uploaded = skipped = missing = 0
    for rel, _required in MANIFEST:
        path = Path(rel)
        if not path.exists():
            print(f"skip (missing locally): {rel}")
            missing += 1
            continue
        url = dir_url + path.name
        local_size = path.stat().st_size
        if not force and remote_size(url, headers) == local_size:
            print(f"up to date, skipping: {rel} ({local_size:,} bytes)")
            skipped += 1
            continue
        snapshot_path = None
        upload_path = path
        if path.suffix == ".db":
            try:
                from backend.adapters.db import create_sqlite_snapshot
                snapshot_path = create_sqlite_snapshot(path)
                upload_path = snapshot_path
            except Exception as exc:
                print(f"could not snapshot {rel} ({exc}); uploading direct")
                upload_path = path

        try:
            data = upload_path.read_bytes()
            req = urllib.request.Request(url, data=data, method="PUT")
            for key, value in headers.items():
                req.add_header(key, value)
            req.add_header("Content-Type", "application/octet-stream")
            started = time.time()
            with urllib.request.urlopen(req, timeout=600) as resp:
                status = resp.status
            elapsed = time.time() - started
            print(f"uploaded {rel} ({len(data) / (1024 * 1024):.1f} MB, HTTP {status}, {elapsed:.1f}s)")
            uploaded += 1
        finally:
            if snapshot_path and snapshot_path.exists():
                try:
                    snapshot_path.unlink()
                except Exception:
                    pass
    print(f"upload summary: {uploaded} uploaded, {skipped} up to date, {missing} missing locally")


def download(env: dict[str, str], dest_root: Path) -> None:
    dir_url = remote_dir_url(env)
    headers = auth_headers(env)

    ok = skipped = incomplete = unavailable = 0
    for rel, required in MANIFEST:
        url = dir_url + Path(rel).name
        target = dest_root / rel
        total = remote_size(url, headers)
        if total is None:
            level = "WARNING" if required else "skip"
            print(f"{level}: not available remotely: {rel}")
            unavailable += 1
            continue

        target.parent.mkdir(parents=True, exist_ok=True)
        existing = target.stat().st_size if target.exists() else 0
        if existing == total:
            print(f"up to date: {rel} ({total:,} bytes)")
            skipped += 1
            continue
        if existing > total:
            print(f"local file larger than remote ({existing:,} > {total:,}); restarting: {rel}")
            target.unlink()
            existing = 0

        print(f"downloading {rel}: {total / (1024 * 1024):.1f} MB"
              + (f" (resume at {existing:,} bytes)" if existing else ""))
        req = urllib.request.Request(url)
        for key, value in headers.items():
            req.add_header(key, value)
        if existing:
            req.add_header("Range", f"bytes={existing}-")
        mode = "ab" if existing else "wb"
        with urllib.request.urlopen(req, timeout=120) as resp, open(target, mode) as out_file:
            last_log = time.time()
            while True:
                chunk = resp.read(1024 * 256)
                if not chunk:
                    break
                out_file.write(chunk)
                now = time.time()
                if now - last_log >= 3.0:
                    size_mb = target.stat().st_size / (1024 * 1024)
                    print(f"  progress: {size_mb:.1f} / {total / (1024 * 1024):.1f} MB")
                    last_log = now
        final = target.stat().st_size
        if final == total:
            print(f"OK: {rel} ({final:,} bytes)")
            ok += 1
        else:
            print(f"INCOMPLETE: {rel} ({final:,}/{total:,} bytes) - rerun to resume")
            incomplete += 1
    print(f"download summary: {ok} downloaded, {skipped} up to date, "
          f"{incomplete} incomplete, {unavailable} unavailable")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=["upload", "download"])
    parser.add_argument("--dest", default=".", help="download destination root (default: repo root)")
    parser.add_argument("--force", action="store_true", help="upload even when sizes match")
    args = parser.parse_args()

    env = load_env()
    if not env.get("WEBDAV_PASSWORD"):
        print("WEBDAV_PASSWORD is not set (environment or .env); cannot authenticate.")
        raise SystemExit(2)

    if args.mode == "upload":
        upload(env, force=args.force)
    else:
        download(env, Path(args.dest))


if __name__ == "__main__":
    main()

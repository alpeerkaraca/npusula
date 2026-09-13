"""Downloads train_dataset.jsonl from Nextcloud WebDAV with resumable chunked streaming.

Credentials come from WEBDAV_URL, WEBDAV_USER and WEBDAV_PASSWORD - the
repository `.env` or the process environment, the latter winning (see
backend/env_loader.py).
"""
import base64
import os
from pathlib import Path
import time
import urllib.request

from backend.env_loader import load_project_env

RAW_DIR = Path("data/raw")
RAW_DIR.mkdir(parents=True, exist_ok=True)
TARGET_FILE = RAW_DIR / "train_dataset.jsonl"


def load_env() -> dict[str, str]:
    """WebDAV settings: process environment first, then the repo `.env`."""
    load_project_env()
    return {
        key: os.environ[key]
        for key in ("WEBDAV_URL", "WEBDAV_USER", "WEBDAV_PASSWORD")
        if os.environ.get(key)
    }


def download_dataset():
    env = load_env()
    base_url = env.get("WEBDAV_URL", "https://cloud.alpeerkaraca.me/remote.php/dav/files/alpeerkaraca/HTWH101/")
    if not base_url.endswith("/"):
        base_url += "/"
    file_url = base_url + "train_dataset.jsonl"
    user = env.get("WEBDAV_USER", "alpeerkaraca")
    pwd = env.get("WEBDAV_PASSWORD", "")

    auth = base64.b64encode(f"{user}:{pwd}".encode()).decode()

    # Get total remote size via HEAD request
    head_req = urllib.request.Request(file_url, method="HEAD")
    head_req.add_header("Authorization", f"Basic {auth}")
    try:
        with urllib.request.urlopen(head_req) as resp:
            total_size = int(resp.headers.get("Content-Length", 458772213))
    except Exception:
        total_size = 458772213

    existing_size = TARGET_FILE.stat().st_size if TARGET_FILE.exists() else 0
    if existing_size >= total_size:
        print(f"File already completely downloaded ({existing_size:,} bytes).")
        return

    print(f"Starting download: {file_url}")
    print(f"Total size: {total_size / (1024 * 1024):.1f} MB (Existing: {existing_size / (1024 * 1024):.1f} MB)")

    req = urllib.request.Request(file_url)
    req.add_header("Authorization", f"Basic {auth}")
    if existing_size > 0:
        req.add_header("Range", f"bytes={existing_size}-")

    mode = "ab" if existing_size > 0 else "wb"
    downloaded = existing_size
    chunk_size = 1024 * 1024  # 1 MB
    start_time = time.time()
    last_log_time = start_time

    with urllib.request.urlopen(req) as response, open(TARGET_FILE, mode) as out_file:
        while True:
            chunk = response.read(chunk_size)
            if not chunk:
                break
            out_file.write(chunk)
            downloaded += len(chunk)

            now = time.time()
            if now - last_log_time >= 3.0 or downloaded >= total_size:
                elapsed = max(now - start_time, 0.001)
                speed_mb = (downloaded - existing_size) / (1024 * 1024) / elapsed
                pct = (downloaded / total_size) * 100.0 if total_size else 0.0
                print(
                    f"Progress: {downloaded / (1024 * 1024):.1f} / {total_size / (1024 * 1024):.1f} MB "
                    f"({pct:.1f}%) - Speed: {speed_mb:.2f} MB/s"
                )
                last_log_time = now

    final_size = TARGET_FILE.stat().st_size
    print(f"Download complete: {final_size:,} bytes saved to {TARGET_FILE}.")


if __name__ == "__main__":
    download_dataset()

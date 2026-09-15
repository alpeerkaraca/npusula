"""Unit tests for Nextcloud WebDAV artifact freshness check and synchronization."""
from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest

from backend.config import settings
from backend.services.artifact_sync import (
    download_artifact,
    query_remote_metadata,
    sync_artifacts_if_outdated,
)


def test_sync_artifacts_skipped_when_no_credentials(monkeypatch):
    monkeypatch.setattr(settings, "WEBDAV_PASSWORD", "")
    result = sync_artifacts_if_outdated()
    assert result["status"] == "skipped"
    assert result["reason"] == "no_credentials"


def test_download_artifact_creates_file_atomically(tmp_path: Path):
    target = tmp_path / "artifacts" / "test_model.txt"
    headers = {"Authorization": "Basic dGVzdDp0ZXN0"}
    content = b"sample model weights binary data"

    mock_resp = MagicMock()
    mock_resp.read.side_effect = [content, b""]
    mock_resp.__enter__.return_value = mock_resp

    with patch("urllib.request.urlopen", return_value=mock_resp):
        success = download_artifact(
            url="https://cloud.example.com/test_model.txt",
            target=target,
            headers=headers,
            expected_size=len(content),
        )

    assert success is True
    assert target.exists()
    assert target.read_bytes() == content


def test_download_artifact_creates_backup_for_sqlite_db(tmp_path: Path):
    target = tmp_path / "data" / "state" / "npusula.db"
    target.parent.mkdir(parents=True, exist_ok=True)
    old_content = b"old sqlite database content"
    new_content = b"new sqlite database content updated from nextcloud"
    target.write_bytes(old_content)

    headers = {"Authorization": "Basic dGVzdDp0ZXN0"}
    mock_resp = MagicMock()
    mock_resp.read.side_effect = [new_content, b""]
    mock_resp.__enter__.return_value = mock_resp

    with patch("urllib.request.urlopen", return_value=mock_resp):
        success = download_artifact(
            url="https://cloud.example.com/npusula.db",
            target=target,
            headers=headers,
            expected_size=len(new_content),
        )

    assert success is True
    assert target.read_bytes() == new_content

    backup = target.with_name("npusula.db.bak")
    assert backup.exists()
    assert backup.read_bytes() == old_content


def test_sync_artifacts_handles_network_error_gracefully(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(settings, "WEBDAV_PASSWORD", "secret123")

    with patch("backend.services.artifact_sync.query_remote_metadata", side_effect=Exception("Connection refused")):
        result = sync_artifacts_if_outdated(dest_root=tmp_path)

    assert result["status"] == "ok"
    assert len(result["errors"]) > 0

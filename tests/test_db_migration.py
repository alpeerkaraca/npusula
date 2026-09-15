"""Unit tests for SQLite database adapter, schemas, and JSON migration."""
import json
from pathlib import Path
import pytest

from backend.adapters.db import get_connection, init_db, migrate_from_json_if_needed
from backend.adapters.repository import SavedContentRepository, UserRepository
from backend.services.profile import ProfileService


def test_init_db_creates_tables(tmp_path: Path):
    db_path = tmp_path / "test.db"
    init_db(db_path)

    with get_connection(db_path) as conn:
        cursor = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name;"
        )
        tables = {row["name"] for row in cursor.fetchall()}

    assert "user_declared_topics" in tables
    assert "user_drift_decisions" in tables
    assert "saved_content" in tables


def test_migrate_from_json(tmp_path: Path):
    db_path = tmp_path / "test_migration.db"
    declared_json = tmp_path / "legacy_declared.json"
    saved_json = tmp_path / "legacy_saved.json"

    # Seed legacy files
    declared_json.write_text(
        json.dumps({
            "user_alpha": ["Yapay Zeka", "Yazılım"],
            "user_beta": ["Spor"],
        }),
        encoding="utf-8",
    )
    saved_json.write_text(
        json.dumps({
            "plan-1": {
                "kind": "plan",
                "slot_id": "1-1",
                "starts_at": "2026-09-16T12:00:00Z",
                "text": "Deneme plan",
            },
            "draft-1": {
                "kind": "draft",
                "text": "Deneme taslak",
            },
        }),
        encoding="utf-8",
    )

    init_db(db_path)
    counts = migrate_from_json_if_needed(
        db_path=db_path,
        declared_path=declared_json,
        saved_path=saved_json,
    )

    assert counts["declared_topics_migrated"] == 3
    assert counts["saved_content_migrated"] == 2

    # Verify through repositories
    user_repo = UserRepository(db_path=db_path)
    assert user_repo.get_declared_profile("user_alpha").declared_topics == ["Yapay Zeka", "Yazılım"]
    assert user_repo.get_declared_profile("user_beta").declared_topics == ["Spor"]

    saved_repo = SavedContentRepository(db_path=db_path)
    assert saved_repo.count() == 2
    assert saved_repo.get("plan-1")["slot_id"] == "1-1"
    assert saved_repo.get("draft-1")["text"] == "Deneme taslak"

    # Second migration must be a no-op (idempotent)
    second_counts = migrate_from_json_if_needed(
        db_path=db_path,
        declared_path=declared_json,
        saved_path=saved_json,
    )
    assert second_counts["declared_topics_migrated"] == 0
    assert second_counts["saved_content_migrated"] == 0


def test_drift_decision_persistence(tmp_path: Path):
    db_path = tmp_path / "test_drift.db"
    service = ProfileService(db_path=db_path)

    service.record_decision("user-100", accept=True)
    assert service._user_decisions["user-100"] is True

    # Reload from fresh service instance
    reloaded_service = ProfileService(db_path=db_path)
    assert reloaded_service._user_decisions.get("user-100") is True

    # Update decision to False
    service.record_decision("user-100", accept=False)
    assert ProfileService(db_path=db_path)._user_decisions.get("user-100") is False

"""Concurrency and locking tests for SQLite database adapter."""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import sqlite3
import pytest

from backend.adapters.db import create_sqlite_snapshot, get_db, init_db
from backend.adapters.repository import SavedContentRepository, UserRepository


def test_sqlite_concurrent_readers_and_writers(tmp_path: Path):
    db_path = tmp_path / "concurrent.db"
    init_db(db_path)

    user_repo = UserRepository(db_path=db_path)
    saved_repo = SavedContentRepository(db_path=db_path)

    def write_user_topics(idx: int):
        user_repo.update_user_declared_topics(f"user_{idx}", [f"Topic_{idx}", "Yazılım"])
        return True

    def write_saved_plan(idx: int):
        saved_repo.put(f"plan_{idx}", {"kind": "plan", "slot_id": f"slot_{idx}", "text": f"Plan {idx}"})
        return True

    def read_user_profile(idx: int):
        profile = user_repo.get_declared_profile(f"user_{idx % 5}")
        return len(profile.declared_topics) >= 0

    def read_saved_count():
        return saved_repo.count() >= 0

    # Run 10 writers and 20 readers concurrently across thread pool
    with ThreadPoolExecutor(max_workers=10) as executor:
        futures = []
        for i in range(15):
            futures.append(executor.submit(write_user_topics, i))
            futures.append(executor.submit(write_saved_plan, i))
            futures.append(executor.submit(read_user_profile, i))
            futures.append(executor.submit(read_saved_count))

        results = [f.result() for f in futures]

    assert all(results)
    assert saved_repo.count() == 15
    assert user_repo.get_declared_profile("user_0").declared_topics == ["Topic_0", "Yazılım"]


def test_create_sqlite_snapshot_vacuum_into(tmp_path: Path):
    db_path = tmp_path / "original.db"
    init_db(db_path)

    user_repo = UserRepository(db_path=db_path)
    user_repo.update_user_declared_topics("snapshot_user", ["Yapay Zeka", "Finans"])

    snapshot_path = create_sqlite_snapshot(db_path)
    assert snapshot_path.exists()
    assert snapshot_path.stat().st_size > 0

    # Verify snapshot can be read as a standalone SQLite database
    snapshot_repo = UserRepository(db_path=snapshot_path)
    profile = snapshot_repo.get_declared_profile("snapshot_user")
    assert profile.declared_topics == ["Yapay Zeka", "Finans"]

    snapshot_path.unlink()

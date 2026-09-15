"""SQLite database adapter for NPusula runtime state.

Provides ACID transaction support, WAL mode concurrency, table schemas,
connection lifecycle management (automatic close), immediate write locks,
snapshotting (hot-backup), and legacy JSON migration.
"""
from contextlib import contextmanager
import json
import logging
import os
from pathlib import Path
import sqlite3
from typing import Any, Generator

from backend.config import settings

logger = logging.getLogger("backend.adapters.db")


def get_connection(db_path: Path | str | None = None) -> sqlite3.Connection:
    """Creates a configured sqlite3 connection with WAL mode and row factory."""
    resolved_path = db_path or settings.SQLITE_DB_PATH
    is_memory = str(resolved_path) == ":memory:"

    if not is_memory:
        Path(resolved_path).parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(
        str(resolved_path),
        timeout=10.0,
        check_same_thread=False,
    )
    conn.row_factory = sqlite3.Row

    if not is_memory:
        conn.execute("PRAGMA journal_mode = WAL;")
        conn.execute("PRAGMA synchronous = NORMAL;")

    conn.execute("PRAGMA foreign_keys = ON;")
    conn.execute("PRAGMA busy_timeout = 5000;")
    return conn


@contextmanager
def get_db(db_path: Path | str | None = None, write: bool = False) -> Generator[sqlite3.Connection, None, None]:
    """Context manager guaranteeing connection closure and immediate write lock to avoid deadlocks."""
    conn = get_connection(db_path)
    is_memory = str(db_path or settings.SQLITE_DB_PATH) == ":memory:"
    try:
        if write and not is_memory:
            conn.execute("BEGIN IMMEDIATE;")
        yield conn
        conn.commit()
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
        raise
    finally:
        conn.close()


def init_db(db_path: Path | str | None = None) -> None:
    """Initializes SQLite schema tables and indexes."""
    with get_db(db_path, write=True) as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS user_declared_topics (
                user_id TEXT NOT NULL,
                topic TEXT NOT NULL,
                topic_order INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                PRIMARY KEY (user_id, topic)
            );
            CREATE INDEX IF NOT EXISTS idx_user_declared_topics_user ON user_declared_topics(user_id);

            CREATE TABLE IF NOT EXISTS user_drift_decisions (
                user_id TEXT PRIMARY KEY,
                accept INTEGER NOT NULL,
                decided_at TEXT NOT NULL DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS saved_content (
                id TEXT PRIMARY KEY,
                kind TEXT NOT NULL,
                slot_id TEXT,
                starts_at TEXT,
                time_zone TEXT,
                text TEXT,
                format TEXT,
                payload_json TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT (datetime('now'))
            );
            CREATE INDEX IF NOT EXISTS idx_saved_content_kind ON saved_content(kind);
        """)
    logger.info("sqlite database initialized at %s", db_path or settings.SQLITE_DB_PATH)


def create_sqlite_snapshot(db_path: Path | str | None = None, dest_path: Path | None = None) -> Path:
    """Creates a consistent, checkpointed standalone SQLite snapshot via VACUUM INTO."""
    resolved_src = Path(db_path or settings.SQLITE_DB_PATH)
    if not resolved_src.exists():
        raise FileNotFoundError(f"source database {resolved_src} does not exist")

    out = dest_path or resolved_src.with_name(f"{resolved_src.stem}_snapshot.db")
    if out.exists():
        out.unlink()
    out.parent.mkdir(parents=True, exist_ok=True)

    with get_db(resolved_src, write=False) as conn:
        posix_path = out.as_posix().replace("'", "''")
        conn.execute(f"VACUUM INTO '{posix_path}';")

    logger.info("created sqlite snapshot: %s -> %s", resolved_src, out)
    return out


def migrate_from_json_if_needed(
    db_path: Path | str | None = None,
    declared_path: Path | None = None,
    saved_path: Path | None = None,
) -> dict[str, int]:
    """Imports legacy JSON state into SQLite if the database tables are empty."""
    resolved_declared = declared_path or settings.DECLARED_TOPICS_PATH
    resolved_saved = saved_path or settings.SAVED_CONTENT_PATH

    counts = {"declared_topics_migrated": 0, "saved_content_migrated": 0}

    with get_db(db_path, write=True) as conn:
        # 1. Migrate declared topics
        cursor = conn.execute("SELECT COUNT(*) FROM user_declared_topics;")
        topics_count = cursor.fetchone()[0]

        if topics_count == 0 and resolved_declared.exists():
            try:
                with open(resolved_declared, "r", encoding="utf-8") as f:
                    declared_data = json.load(f)
                if isinstance(declared_data, dict):
                    to_insert = []
                    for user_id, topics in declared_data.items():
                        if isinstance(topics, list):
                            for order, topic in enumerate(topics):
                                if isinstance(topic, str):
                                    to_insert.append((str(user_id), str(topic), order))
                    if to_insert:
                        conn.executemany(
                            """
                            INSERT OR IGNORE INTO user_declared_topics (user_id, topic, topic_order)
                            VALUES (?, ?, ?);
                            """,
                            to_insert,
                        )
                        counts["declared_topics_migrated"] = len(to_insert)
            except Exception as exc:
                logger.warning("could not migrate declared topics from %s: %s", resolved_declared, exc)

        # 2. Migrate saved content (plans & drafts)
        cursor = conn.execute("SELECT COUNT(*) FROM saved_content;")
        saved_count = cursor.fetchone()[0]

        if saved_count == 0 and resolved_saved.exists():
            try:
                with open(resolved_saved, "r", encoding="utf-8") as f:
                    saved_data = json.load(f)
                if isinstance(saved_data, dict):
                    to_insert_saved = []
                    for record_id, record in saved_data.items():
                        if isinstance(record, dict):
                            kind = str(record.get("kind", "unknown"))
                            slot_id = record.get("slot_id")
                            starts_at = record.get("starts_at")
                            time_zone = record.get("time_zone")
                            text = record.get("text")
                            fmt = record.get("format")
                            payload = json.dumps(record, ensure_ascii=False)
                            to_insert_saved.append((
                                str(record_id), kind, slot_id, starts_at, time_zone, text, fmt, payload
                            ))
                    if to_insert_saved:
                        conn.executemany(
                            """
                            INSERT OR IGNORE INTO saved_content (
                                id, kind, slot_id, starts_at, time_zone, text, format, payload_json
                            )
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?);
                            """,
                            to_insert_saved,
                        )
                        counts["saved_content_migrated"] = len(to_insert_saved)
            except Exception as exc:
                logger.warning("could not migrate saved content from %s: %s", resolved_saved, exc)

    if counts["declared_topics_migrated"] > 0 or counts["saved_content_migrated"] > 0:
        logger.info(
            "migrated legacy JSON data to sqlite: topics=%d items=%d",
            counts["declared_topics_migrated"],
            counts["saved_content_migrated"],
        )
    return counts

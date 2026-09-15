"""Repository adapter for accessing demo users and post records."""
import json
import logging
import os
from pathlib import Path
from typing import Any
import pandas as pd

from backend.adapters.db import get_db, init_db
from backend.config import settings
from backend.schemas.profile import DeclaredProfile

logger = logging.getLogger("backend.adapters.repository")


def _read_json_dict(path: Path) -> dict[str, Any]:
    """Loads a JSON object, tolerating a missing or malformed file.

    Runtime state must never take the API down: a half-written file or a
    read-only volume degrades to an empty dict with a warning.
    """
    if not path.exists():
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("state file %s unreadable (%s); starting empty", path, exc)
        return {}
    return data if isinstance(data, dict) else {}


def _write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    """Writes JSON via a temp file + rename so readers never see a partial file."""
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(f"{path.name}.tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2, ensure_ascii=False)
        os.replace(tmp, path)
    except OSError as exc:
        # The in-process value is still correct, so a failed write is a warning.
        logger.warning("could not persist %s (%s)", path, exc)


class PostRepository:
    """Manages post persistence and retrieval from Parquet."""

    def __init__(self, parquet_path: Path | None = None):
        self.path = parquet_path or settings.PROCESSED_DATA_PATH
        self._df: pd.DataFrame | None = None

    def get_df(self) -> pd.DataFrame:
        if self._df is None:
            if self.path.exists():
                self._df = pd.read_parquet(self.path)
            else:
                self._df = pd.DataFrame()
        return self._df

    def get_user_history(self, user_id: str) -> pd.DataFrame:
        df = self.get_df()
        if df.empty or "user_id" not in df.columns:
            return pd.DataFrame()
        user_df = df[df["user_id"] == user_id].copy()
        if "published_at_utc" in user_df.columns:
            user_df["published_at_utc"] = pd.to_datetime(user_df["published_at_utc"])
            user_df = user_df.sort_values("published_at_utc")
        return user_df

    def get_user_post_counts(self, user_ids: list[str]) -> dict[str, int]:
        """Counts each user's posts without materializing their history.

        get_user_history copies and sorts the matched rows; for a depth label
        only the count is needed, and counting the warm frame vectorized is
        ~4x cheaper across a handful of ids. Users absent from the corpus come
        back as 0, which is what the cold-start branch expects.
        """
        df = self.get_df()
        if df.empty or "user_id" not in df.columns:
            return {user_id: 0 for user_id in user_ids}
        counts = df[df["user_id"].isin(user_ids)]["user_id"].value_counts()
        return {user_id: int(counts.get(user_id, 0)) for user_id in user_ids}

    def get_successful_posts(self, percentile: float = 75.0) -> list[dict[str, Any]]:
        df = self.get_df()
        if df.empty:
            return []
        threshold = df["popularity_score"].quantile(percentile / 100.0)
        filtered = df[df["popularity_score"] >= threshold]
        return filtered.to_dict(orient="records")


class UserRepository:
    """Manages user profiles and demo accounts backed by SQLite."""

    def __init__(
        self,
        demo_path: Path | None = None,
        state_path: Path | None = None,
        db_path: Path | str | None = None,
    ):
        self.path = demo_path or settings.DEMO_ACCOUNTS_PATH
        self.state_path = state_path or settings.DECLARED_TOPICS_PATH
        if db_path is not None:
            self.db_path = db_path
        elif state_path is not None:
            self.db_path = state_path.with_suffix(".db")
        else:
            self.db_path = settings.SQLITE_DB_PATH

        self._accounts: dict[str, dict[str, Any]] = {}
        self._declared: dict[str, list[str]] = {}
        init_db(self.db_path)
        self._load()

    def _load(self) -> None:
        self._accounts = _read_json_dict(self.path)
        self._declared = {}
        try:
            with get_db(self.db_path, write=False) as conn:
                cursor = conn.execute(
                    "SELECT user_id, topic FROM user_declared_topics ORDER BY user_id, topic_order ASC;"
                )
                for row in cursor.fetchall():
                    uid = row["user_id"]
                    topic = row["topic"]
                    if uid not in self._declared:
                        self._declared[uid] = []
                    self._declared[uid].append(topic)
        except Exception as exc:
            logger.warning("could not load declared topics from sqlite %s: %s", self.db_path, exc)

        # Legacy JSON fallback if DB was empty but JSON exists
        if not self._declared and self.state_path.exists():
            for user_id, topics in _read_json_dict(self.state_path).items():
                if isinstance(topics, list):
                    clean = [t for t in topics if isinstance(t, str)]
                    if clean:
                        self._declared[user_id] = clean

    def get_demo_users(self) -> list[dict[str, Any]]:
        return list(self._accounts.values())

    def get_user(self, user_id: str) -> dict[str, Any] | None:
        return self._accounts.get(user_id)

    def get_declared_profile(self, user_id: str) -> DeclaredProfile:
        """Runtime declaration from SQLite wins, then the curated demo roster, then default."""
        if user_id in self._declared:
            return DeclaredProfile(
                user_id=user_id, declared_topics=list(self._declared[user_id])
            )
        try:
            with get_db(self.db_path, write=False) as conn:
                cursor = conn.execute(
                    "SELECT topic FROM user_declared_topics WHERE user_id = ? ORDER BY topic_order ASC;",
                    (user_id,),
                )
                rows = cursor.fetchall()
                if rows:
                    topics = [r["topic"] for r in rows]
                    self._declared[user_id] = topics
                    return DeclaredProfile(user_id=user_id, declared_topics=topics)
        except Exception:
            pass

        acc = self.get_user(user_id)
        if acc:
            return DeclaredProfile(
                user_id=user_id,
                declared_topics=acc.get("declared_topics", ["Teknoloji"]),
            )
        return DeclaredProfile(user_id=user_id, declared_topics=["Teknoloji"])

    def update_user_declared_topics(self, user_id: str, new_topics: list[str]) -> None:
        """Upserts the user's declared topics into SQLite and keeps cache fresh."""
        clean_topics = list(new_topics)
        self._declared[user_id] = clean_topics
        try:
            with get_db(self.db_path, write=True) as conn:
                conn.execute("DELETE FROM user_declared_topics WHERE user_id = ?;", (user_id,))
                conn.executemany(
                    "INSERT INTO user_declared_topics (user_id, topic, topic_order) VALUES (?, ?, ?);",
                    [(user_id, topic, idx) for idx, topic in enumerate(clean_topics)],
                )
        except Exception as exc:
            logger.warning("could not persist declared topics to sqlite: %s", exc)


class SavedContentRepository:
    """Stores plans and drafts the user saves, backed by SQLite.

    The API records intent only. There is no publish step, no scheduling
    authority and no notification, so a stored plan is never presented as
    published (`status` stays "saved").
    """

    def __init__(
        self,
        state_path: Path | None = None,
        db_path: Path | str | None = None,
    ):
        self.state_path = state_path or settings.SAVED_CONTENT_PATH
        if db_path is not None:
            self.db_path = db_path
        elif state_path is not None:
            self.db_path = state_path.with_suffix(".db")
        else:
            self.db_path = settings.SQLITE_DB_PATH

        self._data: dict[str, dict[str, Any]] = {}
        init_db(self.db_path)
        self._load()

    def _load(self) -> None:
        self._data = {}
        try:
            with get_db(self.db_path, write=False) as conn:
                cursor = conn.execute("SELECT id, payload_json FROM saved_content;")
                for row in cursor.fetchall():
                    try:
                        self._data[row["id"]] = json.loads(row["payload_json"])
                    except Exception:
                        pass
        except Exception as exc:
            logger.warning("could not load saved content from sqlite %s: %s", self.db_path, exc)

        if not self._data and self.state_path.exists():
            legacy = _read_json_dict(self.state_path)
            if isinstance(legacy, dict):
                self._data.update(legacy)

    def put(self, record_id: str, record: dict[str, Any]) -> dict[str, Any]:
        self._data[record_id] = record
        kind = str(record.get("kind", "unknown"))
        slot_id = record.get("slot_id")
        starts_at = record.get("starts_at")
        time_zone = record.get("time_zone")
        text = record.get("text")
        fmt = record.get("format")
        payload = json.dumps(record, ensure_ascii=False)

        try:
            with get_db(self.db_path, write=True) as conn:
                conn.execute(
                    """
                    INSERT INTO saved_content (
                        id, kind, slot_id, starts_at, time_zone, text, format, payload_json
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(id) DO UPDATE SET
                        kind = excluded.kind,
                        slot_id = excluded.slot_id,
                        starts_at = excluded.starts_at,
                        time_zone = excluded.time_zone,
                        text = excluded.text,
                        format = excluded.format,
                        payload_json = excluded.payload_json;
                    """,
                    (record_id, kind, slot_id, starts_at, time_zone, text, fmt, payload),
                )
        except Exception as exc:
            logger.warning("could not persist saved content %s to sqlite: %s", record_id, exc)
        return record

    def get(self, record_id: str) -> dict[str, Any] | None:
        if record_id in self._data:
            return self._data[record_id]
        try:
            with get_db(self.db_path, write=False) as conn:
                cursor = conn.execute("SELECT payload_json FROM saved_content WHERE id = ?;", (record_id,))
                row = cursor.fetchone()
                if row:
                    data = json.loads(row["payload_json"])
                    self._data[record_id] = data
                    return data
        except Exception:
            pass
        return None

    def count(self) -> int:
        try:
            with get_db(self.db_path, write=False) as conn:
                cursor = conn.execute("SELECT COUNT(*) FROM saved_content;")
                return int(cursor.fetchone()[0])
        except Exception:
            return len(self._data)

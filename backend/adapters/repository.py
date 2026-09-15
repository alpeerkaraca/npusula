"""Repository adapter for accessing demo users and post records."""
import json
import logging
import os
from pathlib import Path
from typing import Any
import pandas as pd

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
    """Manages user profiles and demo accounts."""

    def __init__(
        self,
        demo_path: Path | None = None,
        state_path: Path | None = None,
    ):
        self.path = demo_path or settings.DEMO_ACCOUNTS_PATH
        self.state_path = state_path or settings.DECLARED_TOPICS_PATH
        self._accounts: dict[str, dict[str, Any]] = {}
        self._declared: dict[str, list[str]] = {}
        self._load()

    def _load(self) -> None:
        self._accounts = _read_json_dict(self.path)
        self._declared = {
            user_id: [topic for topic in topics if isinstance(topic, str)]
            for user_id, topics in _read_json_dict(self.state_path).items()
            if isinstance(topics, list)
        }

    def get_demo_users(self) -> list[dict[str, Any]]:
        return list(self._accounts.values())

    def get_user(self, user_id: str) -> dict[str, Any] | None:
        return self._accounts.get(user_id)

    def get_declared_profile(self, user_id: str) -> DeclaredProfile:
        """Runtime declaration wins, then the curated demo roster, then default."""
        if user_id in self._declared:
            return DeclaredProfile(
                user_id=user_id, declared_topics=list(self._declared[user_id])
            )
        acc = self.get_user(user_id)
        if acc:
            return DeclaredProfile(
                user_id=user_id,
                declared_topics=acc.get("declared_topics", ["Teknoloji"]),
            )
        return DeclaredProfile(user_id=user_id, declared_topics=["Teknoloji"])

    def update_user_declared_topics(self, user_id: str, new_topics: list[str]) -> None:
        """Upserts the user's declared topics and persists them.

        Unlike the previous implementation this accepts users the demo roster
        has never heard of, which is the only case that occurs while
        `demo_accounts.json` is absent. `self.path` (the curated demo roster) is
        deliberately never written: /api/demo-users must keep answering [].
        """
        self._declared[user_id] = list(new_topics)
        _write_json_atomic(self.state_path, self._declared)


class SavedContentRepository:
    """Stores plans and drafts the user saves, keyed by id.

    The API records intent only. There is no publish step, no scheduling
    authority and no notification, so a stored plan is never presented as
    published (`status` stays "saved").
    """

    def __init__(self, state_path: Path | None = None):
        self.state_path = state_path or settings.SAVED_CONTENT_PATH
        self._data: dict[str, dict[str, Any]] = _read_json_dict(self.state_path)

    def put(self, record_id: str, record: dict[str, Any]) -> dict[str, Any]:
        self._data[record_id] = record
        _write_json_atomic(self.state_path, self._data)
        return record

    def get(self, record_id: str) -> dict[str, Any] | None:
        return self._data.get(record_id)

    def count(self) -> int:
        return len(self._data)

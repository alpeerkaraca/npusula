"""Repository adapter for accessing demo users and post records."""
import json
from pathlib import Path
from typing import Any
import pandas as pd

from backend.config import settings
from backend.schemas.profile import DeclaredProfile


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

    def get_successful_posts(self, percentile: float = 75.0) -> list[dict[str, Any]]:
        df = self.get_df()
        if df.empty:
            return []
        threshold = df["popularity_score"].quantile(percentile / 100.0)
        filtered = df[df["popularity_score"] >= threshold]
        return filtered.to_dict(orient="records")


class UserRepository:
    """Manages user profiles and demo accounts."""

    def __init__(self, demo_path: Path | None = None):
        self.path = demo_path or settings.DEMO_ACCOUNTS_PATH
        self._accounts: dict[str, dict[str, Any]] = {}
        self._load()

    def _load(self) -> None:
        if self.path.exists():
            with open(self.path, "r", encoding="utf-8") as f:
                self._accounts = json.load(f)
        else:
            self._accounts = {}

    def get_demo_users(self) -> list[dict[str, Any]]:
        return list(self._accounts.values())

    def get_user(self, user_id: str) -> dict[str, Any] | None:
        return self._accounts.get(user_id)

    def get_declared_profile(self, user_id: str) -> DeclaredProfile:
        acc = self.get_user(user_id)
        if acc:
            return DeclaredProfile(
                user_id=user_id,
                declared_topics=acc.get("declared_topics", ["Teknoloji"]),
            )
        return DeclaredProfile(user_id=user_id, declared_topics=["Teknoloji"])

    def update_user_declared_topics(self, user_id: str, new_topics: list[str]) -> None:
        if user_id in self._accounts:
            self._accounts[user_id]["declared_topics"] = new_topics
            with open(self.path, "w", encoding="utf-8") as f:
                json.dump(self._accounts, f, indent=2, ensure_ascii=False)

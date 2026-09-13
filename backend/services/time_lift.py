"""Layer B — observational time-lift table over 3-hour local windows.

What this layer claims (and what it refuses to claim):

    "Tarihsel gözlemlerde, yeterli örnek bulunan bu kategori-zaman penceresi
     base potansiyele göre pozitif residual lift göstermiştir."

It does **not** claim that the hour causes the lift. The Flickr corpus is
observational, so the layer reports a shrunk mean residual plus a user-clustered
bootstrap interval, and refuses a strict ranking unless support, interval and the
gap to the runner-up all clear the thresholds selected on validation.

Hierarchy (§4.3): category×weekday×bucket → category×bucket → global
weekday×bucket → global bucket → neutral. Every lookup reports which level it
actually used in `evidence_level`.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
import json
from pathlib import Path
from typing import Iterable

import numpy as np

from backend.services.time_features import BUCKET_HOURS, BUCKETS_PER_DAY, format_bucket_range, weekday_name_tr

LEVEL_CATEGORY_WEEKDAY_BUCKET = "category_weekday_bucket"
LEVEL_CATEGORY_BUCKET = "category_bucket"
LEVEL_GLOBAL_WEEKDAY_BUCKET = "global_weekday_bucket"
LEVEL_GLOBAL_BUCKET = "global_bucket"
LEVEL_NEUTRAL = "neutral"

EVIDENCE_LEVELS = (
    LEVEL_CATEGORY_WEEKDAY_BUCKET,
    LEVEL_CATEGORY_BUCKET,
    LEVEL_GLOBAL_WEEKDAY_BUCKET,
    LEVEL_GLOBAL_BUCKET,
    LEVEL_NEUTRAL,
)

CONFIDENCE_HIGH = "high"
CONFIDENCE_MEDIUM = "medium"
CONFIDENCE_LOW = "low"


@dataclass
class TimeLiftConfig:
    """Thresholds. Every value here is selected on the validation split only."""

    bucket_hours: int = BUCKET_HOURS
    shrinkage_k: float = 50.0
    min_support_posts: int = 30
    min_support_users: int = 10
    min_meaningful_lift: float = 0.05
    bootstrap_samples: int = 200
    bootstrap_seed: int = 42
    ci_level: float = 0.90

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class LiftEntry:
    """One group's support, shrunk lift and bootstrap interval."""

    evidence_level: str
    support_post_count: int
    support_user_count: int
    raw_mean_lift: float
    mean_lift: float
    ci_low: float | None
    ci_high: float | None
    eligible: bool
    bucket: int | None = None
    weekday: int | None = None
    category_code: int | None = None

    def to_dict(self) -> dict:
        return asdict(self)


def _key(parts: Iterable[int]) -> str:
    return "|".join(str(int(part)) for part in parts)


def _neutral_entry() -> LiftEntry:
    return LiftEntry(
        evidence_level=LEVEL_NEUTRAL,
        support_post_count=0,
        support_user_count=0,
        raw_mean_lift=0.0,
        mean_lift=0.0,
        ci_low=None,
        ci_high=None,
        eligible=False,
    )


@dataclass
class GroupStats:
    """Bootstrap raw statistics for one group, independent of the shrinkage `k`.

    Separating the (expensive) sampling from the (cheap) shrinkage lets the
    validation search sweep `k` and the support thresholds without re-bootstrapping.
    """

    level: str
    key_parts: tuple[int, ...]
    post_count: int
    user_count: int
    raw_mean: float
    raw_ci_low: float | None
    raw_ci_high: float | None


class TimeLiftTable:
    """Fitted lift table with hierarchical fallback."""

    ARTIFACT_VERSION = "1.0"

    def __init__(
        self,
        config: TimeLiftConfig | None = None,
        levels: dict[str, dict[str, LiftEntry]] | None = None,
        stats: dict[str, dict[str, GroupStats]] | None = None,
    ):
        self.config = config or TimeLiftConfig()
        self.levels: dict[str, dict[str, LiftEntry]] = levels or {level: {} for level in EVIDENCE_LEVELS}
        self.stats: dict[str, dict[str, GroupStats]] = stats or {}
        self.coverage: dict = {}

    # ------------------------------------------------------------------ fit
    @classmethod
    def fit(cls, frame, config: TimeLiftConfig) -> "TimeLiftTable":
        """Builds the table from **training-only** out-of-fold residuals.

        `frame` needs the columns: category_code, local_weekday, bucket,
        user_id, residual. The caller (scripts/06_time_lift.py) is responsible
        for producing residuals that never saw the validation or test splits.
        """
        required = {"category_code", "local_weekday", "bucket", "user_id", "residual"}
        missing = required - set(frame.columns)
        if missing:
            raise ValueError(f"time-lift fit is missing columns: {sorted(missing)}")

        stats = compute_group_stats(
            frame,
            bootstrap_samples=config.bootstrap_samples,
            bootstrap_seed=config.bootstrap_seed,
            ci_level=config.ci_level,
        )
        table = cls(config=config, stats=stats)
        table.levels = build_entries(stats, config)
        table.coverage = table._compute_coverage()
        return table

    def with_config(self, config: TimeLiftConfig) -> "TimeLiftTable":
        """Rebuilds the entries under a new shrinkage/support config.

        Only valid when the bootstrap parameters are unchanged, because the raw
        intervals come from the cached sampling. Used by the validation search.
        """
        if not self.stats:
            raise ValueError("with_config requires a table fitted in this process (no cached statistics).")
        if (
            config.bootstrap_samples != self.config.bootstrap_samples
            or config.ci_level != self.config.ci_level
            or config.bootstrap_seed != self.config.bootstrap_seed
        ):
            raise ValueError("with_config cannot change bootstrap_samples/ci_level/seed; refit instead.")
        table = TimeLiftTable(config=config, stats=self.stats)
        table.levels = build_entries(self.stats, config)
        table.coverage = table._compute_coverage()
        return table

    def _compute_coverage(self) -> dict:
        counts = {level: len(self.levels.get(level, {})) for level in EVIDENCE_LEVELS if level != LEVEL_NEUTRAL}
        eligible = {
            level: sum(1 for entry in self.levels.get(level, {}).values() if entry.eligible)
            for level in counts
        }
        category_weekday = self.levels.get(LEVEL_CATEGORY_WEEKDAY_BUCKET, {})
        supports = sorted(entry.support_post_count for entry in category_weekday.values())
        return {
            "level_group_counts": counts,
            "level_eligible_group_counts": eligible,
            "supported_bucket_count": eligible.get(LEVEL_CATEGORY_WEEKDAY_BUCKET, 0),
            "category_weekday_bucket_support": {
                "min": supports[0] if supports else 0,
                "median": supports[len(supports) // 2] if supports else 0,
                "max": supports[-1] if supports else 0,
            },
        }

    # --------------------------------------------------------------- lookup
    def lookup(self, category_code: int, weekday: int, bucket: int) -> LiftEntry:
        """Resolves a group through the hierarchy, reporting the level actually used.

        A level is used when a group exists there **and** meets the support
        thresholds; otherwise the search widens. `eligible` in the returned entry
        says whether the returned level is strong enough for a strict claim.
        """
        candidates = (
            (LEVEL_CATEGORY_WEEKDAY_BUCKET, _key([category_code, weekday, bucket])),
            (LEVEL_CATEGORY_BUCKET, _key([category_code, bucket])),
            (LEVEL_GLOBAL_WEEKDAY_BUCKET, _key([weekday, bucket])),
            (LEVEL_GLOBAL_BUCKET, _key([bucket])),
        )
        for level, key in candidates:
            entry = self.levels.get(level, {}).get(key)
            if entry is not None and entry.eligible:
                return entry
        # Nothing met the support bar: return the widest informative row, marked
        # ineligible, so the caller still gets a number but cannot claim a ranking.
        for level, key in reversed(candidates):
            entry = self.levels.get(level, {}).get(key)
            if entry is not None:
                return entry
        return _neutral_entry()

    def all_group_keys(self, level: str = LEVEL_CATEGORY_WEEKDAY_BUCKET) -> list[str]:
        return sorted(self.levels.get(level, {}).keys())

    # ------------------------------------------------------------ serialize
    def to_artifact(self, provenance: dict | None = None) -> dict:
        document = {
            "artifact_version": self.ARTIFACT_VERSION,
            "bucket_hours": self.config.bucket_hours,
            "config": self.config.to_dict(),
            "levels": {
                level: {key: entry.to_dict() for key, entry in entries.items()}
                for level, entries in self.levels.items()
                if level != LEVEL_NEUTRAL
            },
            "coverage": self.coverage,
        }
        if provenance:
            document["provenance"] = provenance
        return document

    def save(self, path: Path, provenance: dict | None = None) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(self.to_artifact(provenance), indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

    @classmethod
    def load(cls, path: Path) -> "TimeLiftTable":
        document = json.loads(Path(path).read_text(encoding="utf-8"))
        return cls.from_artifact(document)

    @classmethod
    def from_artifact(cls, document: dict) -> "TimeLiftTable":
        config = TimeLiftConfig(**document.get("config", {}))
        levels: dict[str, dict[str, LiftEntry]] = {level: {} for level in EVIDENCE_LEVELS}
        for level, entries in document.get("levels", {}).items():
            levels[level] = {
                key: LiftEntry(**{**entry, "evidence_level": level})
                for key, entry in entries.items()
            }
        table = cls(config=config, levels=levels)
        table.coverage = document.get("coverage", {})
        return table


LEVEL_KEY_NAMES: dict[str, tuple[str, ...]] = {
    LEVEL_CATEGORY_WEEKDAY_BUCKET: ("category_code", "weekday", "bucket"),
    LEVEL_CATEGORY_BUCKET: ("category_code", "bucket"),
    LEVEL_GLOBAL_WEEKDAY_BUCKET: ("weekday", "bucket"),
    LEVEL_GLOBAL_BUCKET: ("bucket",),
}


def compute_group_stats(
    frame,
    *,
    bootstrap_samples: int = 200,
    bootstrap_seed: int = 42,
    ci_level: float = 0.90,
) -> dict[str, dict[str, GroupStats]]:
    """Groups train residuals and samples the user-clustered bootstrap once."""
    category = frame["category_code"].to_numpy(dtype=int)
    weekday = frame["local_weekday"].to_numpy(dtype=int)
    bucket = frame["bucket"].to_numpy(dtype=int)
    residual = frame["residual"].to_numpy(dtype=float)
    users = frame["user_id"].to_numpy()

    level_columns = {
        LEVEL_CATEGORY_WEEKDAY_BUCKET: np.stack([category, weekday, bucket], axis=1),
        LEVEL_CATEGORY_BUCKET: np.stack([category, bucket], axis=1),
        LEVEL_GLOBAL_WEEKDAY_BUCKET: np.stack([weekday, bucket], axis=1),
        LEVEL_GLOBAL_BUCKET: bucket.reshape(-1, 1),
    }

    tail = (1.0 - ci_level) / 2.0
    all_stats: dict[str, dict[str, GroupStats]] = {level: {} for level in EVIDENCE_LEVELS}

    for level, columns in level_columns.items():
        groups: dict[str, list[int]] = {}
        for index, key_parts in enumerate(columns):
            groups.setdefault(_key(key_parts), []).append(index)

        for key, indices in groups.items():
            index_array = np.asarray(indices)
            group_residuals = residual[index_array]
            group_users = users[index_array]
            post_count = int(group_residuals.size)
            user_labels, inverse = np.unique(group_users, return_inverse=True)
            user_count = int(user_labels.size)
            raw_mean = float(np.mean(group_residuals)) if post_count else 0.0

            raw_ci_low: float | None = None
            raw_ci_high: float | None = None
            if user_count >= 2 and bootstrap_samples > 0:
                # Cluster bootstrap: users are resampled, never individual posts,
                # because posts of the same account are not independent.
                user_sums = np.bincount(inverse, weights=group_residuals, minlength=user_count)
                user_counts = np.bincount(inverse, minlength=user_count).astype(float)
                rng = np.random.default_rng(
                    bootstrap_seed + _stable_seed(level, [int(part) for part in key.split("|")])
                )
                draws = rng.integers(0, user_count, size=(bootstrap_samples, user_count))
                drawn_counts = user_counts[draws].sum(axis=1)
                drawn_sums = user_sums[draws].sum(axis=1)
                valid = drawn_counts > 0
                if valid.any():
                    bootstrap_means = drawn_sums[valid] / drawn_counts[valid]
                    low, high = np.percentile(bootstrap_means, [tail * 100.0, (1.0 - tail) * 100.0])
                    raw_ci_low = float(low)
                    raw_ci_high = float(high)

            all_stats[level][key] = GroupStats(
                level=level,
                key_parts=tuple(int(part) for part in key.split("|")),
                post_count=post_count,
                user_count=user_count,
                raw_mean=raw_mean,
                raw_ci_low=raw_ci_low,
                raw_ci_high=raw_ci_high,
            )
    return all_stats


def build_entries(stats: dict[str, dict[str, GroupStats]], config: TimeLiftConfig) -> dict[str, dict[str, LiftEntry]]:
    """Applies shrinkage and support thresholds to the cached group statistics."""
    entries_by_level: dict[str, dict[str, LiftEntry]] = {}
    for level in EVIDENCE_LEVELS:
        entries: dict[str, LiftEntry] = {}
        for key, group in stats.get(level, {}).items():
            shrink_factor = (
                group.post_count / (group.post_count + config.shrinkage_k) if group.post_count else 0.0
            )
            named = dict(zip(LEVEL_KEY_NAMES[level], group.key_parts))
            entries[key] = LiftEntry(
                evidence_level=level,
                support_post_count=group.post_count,
                support_user_count=group.user_count,
                raw_mean_lift=round(group.raw_mean, 6),
                mean_lift=round(shrink_factor * group.raw_mean, 6),
                # The interval is reported on the shrunk scale, matching `mean_lift`.
                ci_low=None if group.raw_ci_low is None else round(group.raw_ci_low * shrink_factor, 6),
                ci_high=None if group.raw_ci_high is None else round(group.raw_ci_high * shrink_factor, 6),
                eligible=(
                    group.post_count >= config.min_support_posts
                    and group.user_count >= config.min_support_users
                ),
                bucket=named.get("bucket"),
                weekday=named.get("weekday"),
                category_code=named.get("category_code"),
            )
        entries_by_level[level] = entries
    return entries_by_level


def _stable_seed(level: str, key_parts: list[int]) -> int:
    """Deterministic per-group seed so the artifact is reproducible."""
    seed = sum(ord(char) for char in level) * 1000003
    for position, part in enumerate(key_parts):
        seed += (position + 1) * (part + 7) * 7919
    return seed % (2**31 - 1)


@dataclass
class WindowScore:
    """One candidate window with its resolved lift and confidence decision."""

    weekday: int
    bucket: int
    lift: float
    evidence_level: str
    support_post_count: int
    support_user_count: int
    ci_low: float | None
    ci_high: float | None
    eligible: bool
    confidence: str = CONFIDENCE_LOW
    is_tie_or_broad_window: bool = False
    score: float = 0.0
    categories: dict = field(default_factory=dict)

    @property
    def range_label(self) -> str:
        return format_bucket_range(self.bucket)

    @property
    def weekday_label(self) -> str:
        return weekday_name_tr(self.weekday)


def decide_windows(
    base_potential: float,
    scored_windows: list[WindowScore],
    config: TimeLiftConfig,
    *,
    cold_start: bool = False,
    timezone_fallback: bool = False,
    max_windows: int = 3,
) -> list[WindowScore]:
    """Applies the §4.4 decision rule and returns the windows to show the user.

    A strict ranking requires (1) enough support, (2) a bootstrap interval that
    separates from neutral, and (3) a gap to the runner-up above the
    validation-selected threshold. When any of them fails, every returned window
    is flagged `is_tie_or_broad_window` and the caller must present it as a
    choice rather than as "the best hour".
    """
    if not scored_windows:
        return []

    ranked = sorted(scored_windows, key=lambda window: window.lift, reverse=True)
    best = ranked[0]
    runner_up = ranked[1] if len(ranked) > 1 else None

    ci_positive = best.ci_low is not None and best.ci_low > 0.0
    gap_ok = runner_up is None or (best.lift - runner_up.lift) >= config.min_meaningful_lift
    supported = best.eligible
    degraded = cold_start or timezone_fallback

    if degraded or not supported or not ci_positive:
        confidence = CONFIDENCE_LOW
    elif gap_ok:
        confidence = CONFIDENCE_HIGH
    else:
        confidence = CONFIDENCE_MEDIUM

    strict_ranking = supported and ci_positive and gap_ok and not degraded
    selected = ranked[:max_windows]

    for window in selected:
        window.confidence = confidence
        window.is_tie_or_broad_window = not strict_ranking
        window.score = round(base_potential + window.lift, 4)
    return selected


def confidence_tr(confidence: str) -> str:
    """Turkish label for API/UI display."""
    return {
        CONFIDENCE_HIGH: "Yüksek",
        CONFIDENCE_MEDIUM: "Orta",
        CONFIDENCE_LOW: "Düşük",
    }.get(confidence, "Düşük")


def supported_bucket_count(table: TimeLiftTable, weekday: int | None = None) -> int:
    """Number of category×weekday×bucket groups eligible for a strict claim."""
    entries = table.levels.get(LEVEL_CATEGORY_WEEKDAY_BUCKET, {})
    return sum(
        1
        for entry in entries.values()
        if entry.eligible and (weekday is None or entry.weekday == weekday)
    )


__all__ = [
    "TimeLiftConfig",
    "TimeLiftTable",
    "LiftEntry",
    "GroupStats",
    "compute_group_stats",
    "build_entries",
    "WindowScore",
    "decide_windows",
    "confidence_tr",
    "supported_bucket_count",
    "LEVEL_CATEGORY_WEEKDAY_BUCKET",
    "LEVEL_CATEGORY_BUCKET",
    "LEVEL_GLOBAL_WEEKDAY_BUCKET",
    "LEVEL_GLOBAL_BUCKET",
    "LEVEL_NEUTRAL",
    "CONFIDENCE_HIGH",
    "CONFIDENCE_MEDIUM",
    "CONFIDENCE_LOW",
    "BUCKETS_PER_DAY",
]

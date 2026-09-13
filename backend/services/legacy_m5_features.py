"""Legacy `M5` feature vector — kept only for the same-protocol comparison.

The production model is Layer A (content + history, no time). This module
reconstructs the *old* 36-column vector so `scripts/evaluate_final.py` can report
"M5 under the locked split" next to the two-layer result, as the plan requires
(§10: "eski ve yeni modelin metriklerini aynı veri/split protokolü altında
karşılaştır").

Nothing in the runtime imports this. It is a historical reproduction, including
the two defects the plan calls out:
  - time-of-day features (`hour`, `weekday`, `month`, cyclical encodings,
    `cat_x_hour`, `cat_x_weekday`, `history_x_hour`) inside the content model,
  - `account_baseline` used both as the residual offset *and* as an input.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from backend.services.tag_taxonomy import align_tags

LEGACY_TIME_FEATURES = [
    "hour",
    "weekday",
    "hour_sin",
    "hour_cos",
    "weekday_sin",
    "weekday_cos",
    "is_weekend",
    "time_basis_utc_fallback",
    "month",
]

LEGACY_TAG_FEATURES = [
    "accepted_tag_count",
    "rejected_tag_count",
    "generic_tag_count",
    "semantic_tag_ratio",
    "irrelevant_tag_ratio",
    "tag_alignment_mean",
    "tag_alignment_min",
    "tag_category_entropy",
]

LEGACY_INTERACTION_FEATURES = [
    "cat_x_hour",
    "cat_x_weekday",
    "history_x_hour",
]

# The legacy taxonomy compared canonical category *names* ("technology") against
# tag-domain names ("tech_software"), so a matched tag never scored 1.0 in
# practice: every accepted tag scored 0.5. Reproduced here faithfully.
LEGACY_ALIGNMENT_SCORE = 0.5


def legacy_tag_features(frame: pd.DataFrame, categories: list[str]) -> pd.DataFrame:
    """Rebuilds the legacy tag columns from the shared tag classifier."""
    rows = []
    tags_series = frame.get("tags", pd.Series([[]] * len(frame), index=frame.index))
    for position, raw_tags in enumerate(tags_series.tolist()):
        safe_tags = list(raw_tags) if isinstance(raw_tags, (list, tuple, np.ndarray)) else []
        result = align_tags(safe_tags, context_category=categories[position])
        total = max(int(result["total_tag_count"]), 1)
        matched = result["aligned_tag_count"] + result["mismatched_tag_count"]
        rows.append({
            "accepted_tag_count": float(matched),
            "rejected_tag_count": float(result["unknown_tag_count"]),
            "generic_tag_count": float(result["generic_tag_count"]),
            "semantic_tag_ratio": float(matched / total),
            "irrelevant_tag_ratio": float(result["unknown_tag_count"] / total),
            "tag_alignment_mean": LEGACY_ALIGNMENT_SCORE if matched else 0.0,
            "tag_alignment_min": LEGACY_ALIGNMENT_SCORE if matched else 0.0,
            "tag_category_entropy": float(result["tag_category_entropy"]),
        })
    return pd.DataFrame(rows, index=frame.index, columns=LEGACY_TAG_FEATURES)


def build_legacy_m5_frame(base_features: pd.DataFrame, frame: pd.DataFrame, categories: list[str]) -> pd.DataFrame:
    """Composes the legacy 36-column vector from Layer A features plus time."""
    legacy = base_features[
        [
            "primary_cat_code",
            "primary_subcat_code",
            "primary_cat_confidence",
            "has_secondary_cat",
            "context_source_code",
            "media_type_code",
            "history_depth_code",
            *[f"text_svd_{index}" for index in range(8)],
        ]
    ].copy()

    hours = frame["local_hour"].astype(float)
    weekdays = frame["local_weekday"].astype(float)
    timestamps = pd.to_datetime(frame["published_at_utc"], utc=True)

    legacy["hour"] = hours
    legacy["weekday"] = weekdays
    legacy["hour_sin"] = np.sin(2 * np.pi * hours / 24.0)
    legacy["hour_cos"] = np.cos(2 * np.pi * hours / 24.0)
    legacy["weekday_sin"] = np.sin(2 * np.pi * weekdays / 7.0)
    legacy["weekday_cos"] = np.cos(2 * np.pi * weekdays / 7.0)
    legacy["is_weekend"] = (weekdays >= 5).astype(float)
    legacy["time_basis_utc_fallback"] = (
        frame["timezone_basis"].astype(str) == "utc_fallback"
    ).astype(float)
    legacy["month"] = timestamps.dt.month.astype(float)

    legacy = pd.concat([legacy, legacy_tag_features(frame, categories)], axis=1)

    legacy["cat_x_hour"] = legacy["primary_cat_code"] * 100 + legacy["hour"]
    legacy["cat_x_weekday"] = legacy["primary_cat_code"] * 10 + legacy["weekday"]
    legacy["history_x_hour"] = legacy["history_depth_code"] * 100 + legacy["hour"]
    # The legacy defect: the offset is also an input.
    legacy["account_baseline"] = base_features["account_baseline"]

    ordered = (
        LEGACY_TIME_FEATURES
        + ["account_baseline", "history_depth_code"]
        + ["primary_cat_code", "primary_subcat_code", "primary_cat_confidence", "has_secondary_cat"]
        + ["context_source_code"]
        + LEGACY_TAG_FEATURES
        + LEGACY_INTERACTION_FEATURES
        + ["media_type_code"]
        + [f"text_svd_{index}" for index in range(8)]
    )
    return legacy[ordered]


__all__ = ["build_legacy_m5_frame", "legacy_tag_features", "LEGACY_TIME_FEATURES"]

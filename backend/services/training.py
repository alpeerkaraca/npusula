"""Shared training/evaluation helpers for the two-layer pipeline.

Everything here is deliberately split-aware: every statistic that reaches a
model, an artifact or a metric is computed from the split it is allowed to see
(train-only medians and vocabulary, validation-only tuning, test read once).

Used by `scripts/05_train_lgbm.py`, `scripts/tune_lgbm.py`,
`scripts/06_time_lift.py` and `scripts/evaluate_final.py`.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import joblib
import lightgbm as lgb
import numpy as np
import pandas as pd
from scipy.stats import spearmanr
from sklearn.decomposition import TruncatedSVD
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics import mean_absolute_error
from sklearn.pipeline import Pipeline

from backend.config import settings
from backend.services.canonical_taxonomy import CANONICAL_CATEGORIES
from backend.services.recommendation import (
    A2_FEATURES,
    A3_FEATURES,
    RecommendationService,
    get_history_depth_code,
)
from backend.services.time_features import bucket_of_hour

TRAIN_FRACTION = 0.70
VALIDATION_FRACTION = 0.15

DEFAULT_LGBM_PARAMS: dict[str, Any] = {
    "n_estimators": 500,
    "learning_rate": 0.05,
    "num_leaves": 127,
    "min_child_samples": 20,
    "subsample": 0.85,
    "colsample_bytree": 0.8,
    "reg_alpha": 0.0,
    "reg_lambda": 5.0,
    "random_state": 42,
    "n_jobs": -1,
    "verbosity": -1,
}


@dataclass(frozen=True)
class SplitBounds:
    """Chronological 70/15/15 boundaries with the timestamps that define them."""

    n_rows: int
    train_end: int
    validation_end: int

    @property
    def train_rows(self) -> int:
        return self.train_end

    @property
    def validation_rows(self) -> int:
        return self.validation_end - self.train_end

    @property
    def test_rows(self) -> int:
        return self.n_rows - self.validation_end

    def to_dict(self, frame: pd.DataFrame) -> dict:
        timestamps = pd.to_datetime(frame["published_at_utc"])
        return {
            "strategy": "chronological_70_15_15",
            "train_rows": self.train_rows,
            "validation_rows": self.validation_rows,
            "test_rows": self.test_rows,
            "train_end_utc": str(timestamps.iloc[self.train_end - 1]),
            "validation_end_utc": str(timestamps.iloc[self.validation_end - 1]),
            "test_start_utc": str(timestamps.iloc[self.validation_end]),
        }


def compute_split_bounds(n_rows: int) -> SplitBounds:
    train_end = int(n_rows * TRAIN_FRACTION)
    validation_end = int(n_rows * (TRAIN_FRACTION + VALIDATION_FRACTION))
    if train_end == 0 or validation_end <= train_end or validation_end >= n_rows:
        raise ValueError("Dataset is too small for a 70/15/15 chronological split.")
    return SplitBounds(n_rows=n_rows, train_end=train_end, validation_end=validation_end)


def load_chronological_frame(parquet_path: Path) -> pd.DataFrame:
    """Loads posts.parquet sorted by UTC time and validates the timezone contract."""
    frame = pd.read_parquet(parquet_path)
    for column in ("local_hour", "local_weekday", "timezone_basis"):
        if column not in frame.columns:
            raise ValueError(
                f"{parquet_path} has no '{column}' column: run scripts/02_normalize_smp.py first "
                "(real local time is required by the two-layer design)."
            )
    frame["published_at_utc"] = pd.to_datetime(frame["published_at_utc"], utc=True)
    return frame.sort_values("published_at_utc").reset_index(drop=True)


def add_bucket_column(frame: pd.DataFrame, bucket_hours: int = 3) -> pd.DataFrame:
    """Adds the local 3-hour (or configured) bucket index used by Layer B."""
    divisor = max(1, bucket_hours)
    if bucket_hours == 3:
        buckets = frame["local_hour"].apply(bucket_of_hour)
    else:
        buckets = (frame["local_hour"].astype(int) // divisor)
    out = frame.copy()
    out["time_bucket"] = buckets.astype(int)
    out["time_bucket_hours"] = bucket_hours
    return out


def build_recommendation_service(default_popularity: float) -> RecommendationService:
    """Training-time service that never touches the production model or metrics.

    Layer A is fitted by the caller, so the booster path stays a placeholder: a
    training run must never silently load (and therefore never overwrite) the
    production model. The time-lift table is read from its real path because it
    is never used on this code path — only `recommend_windows` consults it — and
    loading it keeps the log honest instead of reporting a missing artifact.
    """
    placeholder = Path("artifacts/.training-placeholder")
    service = RecommendationService(
        model_path=placeholder.with_suffix(".txt"),
        time_lift_path=settings.TIME_LIFT_PATH,
        metrics_path=placeholder.with_suffix(".metrics.json"),
    )
    service.default_popularity = default_popularity
    return service


def fit_svd_pipeline(train_titles: pd.Series, output_path: Path, n_components: int = 8) -> Pipeline:
    """Fits TF-IDF + SVD on **train titles only** and persists the pipeline."""
    pipeline = Pipeline([
        ("tfidf", TfidfVectorizer(max_features=5000, sublinear_tf=True)),
        ("svd", TruncatedSVD(n_components=n_components, random_state=42)),
    ])
    pipeline.fit(train_titles.fillna("").astype(str))
    output_path.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(pipeline, output_path)
    return pipeline


def fit_train_statistics(service: RecommendationService, y_train: np.ndarray, categories_train: np.ndarray) -> dict:
    """Sets the global mean and category medians from the train window only."""
    service.default_popularity = float(np.mean(y_train))
    codes = pd.Series(np.asarray(categories_train, dtype=int))
    medians = pd.Series(np.asarray(y_train, dtype=float)).groupby(codes).median()
    service.category_train_medians = {int(code): float(value) for code, value in medians.items()}
    return {"global_train_mean": service.default_popularity, "category_train_medians": service.category_train_medians}


def fit_base_model(
    X_train: pd.DataFrame,
    y_train_residual: np.ndarray,
    X_val: pd.DataFrame,
    y_val_residual: np.ndarray,
    *,
    objective: str = "quantile",
    alpha: float = 0.55,
    params: dict[str, Any] | None = None,
    early_stopping_rounds: int = 50,
) -> lgb.LGBMRegressor:
    """Fits Layer A on the residual target with early stopping on validation."""
    resolved = {**DEFAULT_LGBM_PARAMS, **(params or {})}
    if objective == "quantile":
        objective_params: dict[str, Any] = {"objective": "quantile", "alpha": alpha}
    else:
        objective_params = {"objective": "regression_l1"}
    model = lgb.LGBMRegressor(**objective_params, **resolved)
    callbacks = [lgb.early_stopping(early_stopping_rounds, verbose=False)] if early_stopping_rounds else None
    eval_set = [(X_val, y_val_residual)] if len(X_val) else None
    model.fit(X_train, y_train_residual, eval_set=eval_set, callbacks=callbacks)
    return model


def expanding_window_oof_residuals(
    X: pd.DataFrame,
    y_residual: np.ndarray,
    train_end: int,
    *,
    objective: str = "quantile",
    alpha: float = 0.55,
    params: dict[str, Any] | None = None,
    n_folds: int = 5,
) -> np.ndarray:
    """Chronologically valid train predictions for the time-lift table (§4.2).

    The train window is cut into consecutive blocks; block *i* is predicted by a
    model fitted only on blocks ``< i``. The first block has no history, so its
    prediction is 0 (i.e. the base prediction is the account offset itself) —
    documented in the artifact rather than hidden.

    Early stopping is disabled inside the folds on purpose: selecting the
    iteration count on the block being predicted would leak that block's target
    straight into the residuals the lift table is built from.
    """
    fold_edges = np.linspace(0, train_end, n_folds + 1).astype(int)
    predictions = np.zeros(train_end, dtype=float)
    for fold in range(n_folds):
        start, end = int(fold_edges[fold]), int(fold_edges[fold + 1])
        if end <= start:
            continue
        if fold == 0:
            continue  # prediction stays 0.0 (offset only)
        resolved = {**DEFAULT_LGBM_PARAMS, **(params or {})}
        resolved["n_estimators"] = int(resolved.get("n_estimators", 500))
        model = fit_base_model(
            X.iloc[:start],
            y_residual[:start],
            X.iloc[start:end],
            y_residual[start:end],
            objective=objective,
            alpha=alpha,
            params=resolved,
            early_stopping_rounds=0,
        )
        predictions[start:end] = model.predict(X.iloc[start:end])
    return predictions


def pinball_loss(y_true: np.ndarray, predictions: np.ndarray, alpha: float) -> float:
    """Quantile (pinball) loss; alpha=0.5 reproduces L1/2."""
    delta = y_true - predictions
    return float(np.mean(np.maximum(alpha * delta, (alpha - 1.0) * delta)))


def _spearman(y_true: np.ndarray, predictions: np.ndarray) -> float:
    if len(y_true) < 2 or np.all(predictions == predictions[0]):
        return 0.0
    value = spearmanr(y_true, predictions).statistic
    return 0.0 if not np.isfinite(value) else float(value)


def base_potential_metrics(
    y_true: np.ndarray,
    predictions: np.ndarray,
    *,
    alpha: float = 0.5,
    tail_percentile: float = 80.0,
) -> dict:
    """Layer A metrics: MAE, median AE, Spearman, pinball, tail, bias (§5.2.B)."""
    if len(y_true) == 0:
        return {}
    errors = np.abs(y_true - predictions)
    threshold = float(np.percentile(y_true, tail_percentile))
    tail_mask = y_true >= threshold
    tail = {
        "percentile": tail_percentile,
        "threshold": round(threshold, 6),
        "count": int(tail_mask.sum()),
    }
    if tail_mask.any():
        tail["tail_mae"] = round(float(mean_absolute_error(y_true[tail_mask], predictions[tail_mask])), 6)
        tail["tail_bias"] = round(float(np.mean(predictions[tail_mask] - y_true[tail_mask])), 6)
    return {
        "count": int(len(y_true)),
        "mae": round(float(mean_absolute_error(y_true, predictions)), 6),
        "median_ae": round(float(np.median(errors)), 6),
        "spearman": round(_spearman(y_true, predictions), 6),
        "pinball_loss": round(pinball_loss(y_true, predictions, alpha), 6),
        "pinball_alpha": alpha,
        "prediction_bias": round(float(np.mean(predictions - y_true)), 6),
        "calibration": {
            "prediction_mean": round(float(np.mean(predictions)), 6),
            "target_mean": round(float(np.mean(y_true)), 6),
            "bias": round(float(np.mean(predictions - y_true)), 6),
        },
        "tail": tail,
    }


def subgroup_metrics(frame: pd.DataFrame, y_true: np.ndarray, predictions: np.ndarray, *, alpha: float = 0.5) -> dict:
    """Overall plus cold-start, history-depth, timezone-basis, category and media cuts."""
    groups: dict[str, dict] = {}

    def record(name: str, mask: np.ndarray) -> None:
        count = int(np.asarray(mask).sum())
        if count:
            groups[name] = base_potential_metrics(y_true[mask], predictions[mask], alpha=alpha)

    if "history_depth_code" in frame.columns:
        depths = frame["history_depth_code"].to_numpy(dtype=int)
    else:
        depths = history_depth_codes(frame["user_post_count_prior"].fillna(0).to_numpy(dtype=int))
    for code, name in enumerate(["cold_start", "very_low_history", "low_history", "medium_history", "high_history"]):
        record(f"history_depth:{name}", depths == code)

    basis = frame["timezone_basis"].astype(str).to_numpy()
    record("timezone:source_offset", basis == "source_offset")
    record("timezone:utc_fallback", basis == "utc_fallback")

    media = frame["media_type"].astype(str).to_numpy()
    record("media:photo", media == "photo")
    record("media:video", media == "video")
    record("media:unknown", media == "unknown")

    categories = frame["primary_cat_code"].astype(int).to_numpy()
    for code, name in enumerate(CANONICAL_CATEGORIES):
        record(f"category:{name}", categories == code)

    return groups


def history_depth_codes(user_post_counts: np.ndarray) -> np.ndarray:
    return np.array([get_history_depth_code(int(count)) for count in user_post_counts], dtype=int)


__all__ = [
    "SplitBounds",
    "compute_split_bounds",
    "load_chronological_frame",
    "add_bucket_column",
    "build_recommendation_service",
    "fit_svd_pipeline",
    "fit_train_statistics",
    "fit_base_model",
    "expanding_window_oof_residuals",
    "pinball_loss",
    "base_potential_metrics",
    "subgroup_metrics",
    "history_depth_codes",
    "DEFAULT_LGBM_PARAMS",
    "A2_FEATURES",
    "A3_FEATURES",
]

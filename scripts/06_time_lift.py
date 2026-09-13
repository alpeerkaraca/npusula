"""Builds Layer B: the observational time-lift table.

Input is **train-only, chronologically valid** data:

  * base predictions come from an expanding-window out-of-fold fit inside the
    train window (never from the model's in-sample fit, which would leak the
    residual the table is measuring),
  * residuals are ``popularity - base_prediction`` for train posts,
  * the thresholds come from the validation-only search in tune_lgbm.py,
  * validation and test rows are never used to estimate a lift.

Output: artifacts/time_lift_table.json
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import time

import numpy as np
import pandas as pd

from backend.services.provenance import (
    file_sha256,
    git_code_is_dirty,
    git_commit_sha,
    git_is_dirty,
    utc_now_iso,
    write_json_with_provenance,
)
from backend.services.recommendation import A3_FEATURES
from backend.services.time_lift import TimeLiftConfig, TimeLiftTable
from backend.services.training import (
    add_bucket_column,
    build_recommendation_service,
    compute_split_bounds,
    expanding_window_oof_residuals,
    fit_train_statistics,
    load_chronological_frame,
)

PARQUET_FILE = Path("data/processed/posts.parquet")
TUNING_INPUT = Path("artifacts/tuning_results.json")
SVD_INPUT = Path("artifacts/text_svd_model.joblib")
TIME_LIFT_OUTPUT = Path("artifacts/time_lift_table.json")

DEFAULT_BUCKET_HOURS = 3


def load_selected_config(path: Path = TUNING_INPUT) -> dict:
    """Reads the validation-selected model + Layer B configuration."""
    if not path.exists():
        raise FileNotFoundError(
            f"{path} is missing: run scripts/tune_lgbm.py first so the bucket size, shrinkage and "
            "support thresholds are validation-selected rather than guessed."
        )
    document = json.loads(path.read_text(encoding="utf-8"))
    selected = document["selected"]
    return {
        "objective": selected["objective"],
        "alpha": selected["alpha"],
        "lgbm_params": selected["lgbm_params"],
        "time_lift": selected["time_lift"],
    }


def build(limit_rows: int | None = None) -> dict:
    started = time.time()
    config = load_selected_config()
    layer_config = TimeLiftConfig(**config["time_lift"])
    print(
        f"Layer B config (validation-selected): bucket={layer_config.bucket_hours}h "
        f"k={layer_config.shrinkage_k} support>={layer_config.min_support_posts}posts/"
        f"{layer_config.min_support_users}users min_lift={layer_config.min_meaningful_lift}"
    )

    frame = load_chronological_frame(PARQUET_FILE)
    if limit_rows:
        frame = frame.iloc[:limit_rows].reset_index(drop=True)
        print(f"[smoke mode] limited to {len(frame):,} rows")
    frame = add_bucket_column(frame, layer_config.bucket_hours)
    bounds = compute_split_bounds(len(frame))

    y = pd.to_numeric(frame["popularity_score"], errors="coerce").fillna(5.8).to_numpy(dtype=float)
    service = build_recommendation_service(default_popularity=float(np.mean(y[: bounds.train_end])))
    if SVD_INPUT.exists():
        import joblib

        service.svd_pipeline = joblib.load(SVD_INPUT)
    else:
        print(f"WARNING: {SVD_INPUT} not found; text features degrade to zeros for the OOF fits.")

    X = service._prepare_features(frame)
    stats = fit_train_statistics(service, y[: bounds.train_end], X.iloc[: bounds.train_end]["primary_cat_code"].to_numpy())
    baseline = service.account_baseline(frame, categories=X["primary_cat_code"].to_numpy())

    residual_train = y[: bounds.train_end] - baseline[: bounds.train_end]
    print("Computing expanding-window OOF base predictions inside the train window...")
    oof_predictions = expanding_window_oof_residuals(
        X[A3_FEATURES],
        residual_train,
        bounds.train_end,
        objective=config["objective"],
        alpha=config["alpha"] if config["alpha"] is not None else 0.55,
        params=config["lgbm_params"],
    )

    train_residuals = pd.DataFrame({
        "category_code": X.iloc[: bounds.train_end]["primary_cat_code"].to_numpy(dtype=int),
        "local_weekday": frame.iloc[: bounds.train_end]["local_weekday"].to_numpy(dtype=int),
        "bucket": frame.iloc[: bounds.train_end]["time_bucket"].to_numpy(dtype=int),
        "user_id": frame.iloc[: bounds.train_end]["user_id"].to_numpy(),
        "residual": residual_train - oof_predictions,
    })
    print(f"Fitting the lift table on {len(train_residuals):,} train residuals (train-only)...")
    table = TimeLiftTable.fit(train_residuals, layer_config)

    provenance = {
        "git_commit": git_commit_sha(),
        "git_dirty": git_code_is_dirty(),
        "git_worktree_dirty": git_is_dirty(),
        "built_at_utc": utc_now_iso(),
        "dataset_parquet": str(PARQUET_FILE),
        "dataset_sha256": file_sha256(PARQUET_FILE),
        "tuning_source": str(TUNING_INPUT),
        "residual_source": "expanding_window_oof_train_predictions",
        "oof_folds": 5,
        "first_fold_note": (
            "The oldest 1/5 of the train window has no preceding history, so its base prediction is the "
            "account offset itself (residual measured against the offset, not against a content model)."
        ),
        "rows_used": int(len(train_residuals)),
        "validation_rows_used": 0,
        "test_rows_used": 0,
        "split_protocol": "chronological_train_validation_locked_test",
        "statistics": stats,
    }
    table.save(TIME_LIFT_OUTPUT, provenance)

    coverage = table.coverage
    print("=" * 60)
    print("Time-lift table built")
    print(f"Groups per level:          {coverage['level_group_counts']}")
    print(f"Eligible groups per level: {coverage['level_eligible_group_counts']}")
    print(f"Supported category×weekday×bucket groups: {coverage['supported_bucket_count']}")
    print(f"Saved to:                  {TIME_LIFT_OUTPUT}")
    print(f"Elapsed:                   {round(time.time() - started, 1)}s")
    print("=" * 60)
    return table.to_artifact(provenance)


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit-rows", type=int, default=None, help="Smoke-test only.")
    return parser.parse_args(argv)


if __name__ == "__main__":
    arguments = _parse_args()
    build(limit_rows=arguments.limit_rows)

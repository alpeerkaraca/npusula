"""Trains Layer A (base potential) with the ablation ladder A0-A4.

Split protocol (plan §2.1): train 70% fits models, validation 15% selects the
variant and the hyperparameters, and the test 15% is **never read here** — only
`scripts/evaluate_final.py` reads it, once, after selection is locked.

Ablations:
    A0  category/global baseline only (no account history)      — lower bound
    A1  account offset only (`account_baseline`)                — history contribution
    A2  A1 + content model (category/tag/text/history/context)  — content contribution
    A3  A2 + media type                                          — production candidate
    A4  legacy M5 vector (time features + baseline as input)     — comparison only

Outputs:
    artifacts/base_potential_lgbm.txt     (production booster)
    artifacts/base_potential_metrics.json (validation metrics + provenance)
    artifacts/text_svd_model.joblib       (train-only TF-IDF + SVD)
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import time

import numpy as np
import pandas as pd

from backend.services.canonical_taxonomy import canonical_name
from backend.services.legacy_m5_features import build_legacy_m5_frame
from backend.services.provenance import (
    file_sha256,
    git_code_is_dirty,
    git_commit_sha,
    git_is_dirty,
    utc_now_iso,
    write_json_with_provenance,
)
from backend.services.recommendation import A2_FEATURES, A3_FEATURES
from backend.services.training import (
    add_bucket_column,
    base_potential_metrics,
    build_recommendation_service,
    compute_split_bounds,
    fit_base_model,
    fit_svd_pipeline,
    fit_train_statistics,
    load_chronological_frame,
    subgroup_metrics,
)
from backend.services.time_lift import TimeLiftConfig

PARQUET_FILE = Path("data/processed/posts.parquet")
DATA_QUALITY_REPORT = Path("data/reports/data_quality.json")
MODEL_OUTPUT = Path("artifacts/base_potential_lgbm.txt")
METRICS_OUTPUT = Path("artifacts/base_potential_metrics.json")
SVD_OUTPUT = Path("artifacts/text_svd_model.joblib")
TUNING_INPUT = Path("artifacts/tuning_results.json")

PRODUCTION_CANDIDATES = ("A2", "A3")


def load_selected_config(path: Path = TUNING_INPUT) -> dict:
    """Reads the validation-selected configuration produced by tune_lgbm.py."""
    if not path.exists():
        return {
            "source": "defaults (artifacts/tuning_results.json not found)",
            "objective": "quantile",
            "alpha": 0.55,
            "lgbm_params": {},
            "bucket_hours": 3,
            "time_lift": TimeLiftConfig().to_dict(),
        }
    document = json.loads(path.read_text(encoding="utf-8"))
    selected = document.get("selected", {})
    return {
        "source": str(path),
        "objective": selected.get("objective", "quantile"),
        "alpha": float(selected.get("alpha", 0.55)),
        "lgbm_params": selected.get("lgbm_params", {}),
        "bucket_hours": int(selected.get("bucket_hours", 3)),
        "time_lift": selected.get("time_lift", TimeLiftConfig().to_dict()),
    }


def _category_baseline(categories: np.ndarray, category_medians: dict[int, float], global_mean: float) -> np.ndarray:
    return np.array(
        [category_medians.get(int(code), global_mean) for code in categories], dtype=float
    )


def train(limit_rows: int | None = None) -> dict:
    started = time.time()
    config = load_selected_config()
    print(f"Selected configuration source: {config['source']}")

    print(f"Loading chronological dataset from {PARQUET_FILE}...")
    frame = load_chronological_frame(PARQUET_FILE)
    if limit_rows:
        frame = frame.iloc[:limit_rows].reset_index(drop=True)
        print(f"[smoke mode] limited to {len(frame):,} rows")
    frame = add_bucket_column(frame, config["bucket_hours"])

    bounds = compute_split_bounds(len(frame))
    train_end, validation_end = bounds.train_end, bounds.validation_end
    print(
        f"Split: train={bounds.train_rows:,} validation={bounds.validation_rows:,} test={bounds.test_rows:,} "
        "(test is not read by this script)"
    )

    y = pd.to_numeric(frame["popularity_score"], errors="coerce").fillna(5.8).to_numpy(dtype=float)

    print("Fitting title-only TF-IDF + SVD on the oldest 70%...")
    svd_pipeline = fit_svd_pipeline(
        frame.iloc[:train_end]["title"], SVD_OUTPUT, n_components=8
    )

    service = build_recommendation_service(default_popularity=1.0)
    service.svd_pipeline = svd_pipeline
    X = service._prepare_features(frame)
    stats = fit_train_statistics(service, y[:train_end], X.iloc[:train_end]["primary_cat_code"].to_numpy())
    baseline = service.account_baseline(frame, categories=X["primary_cat_code"].to_numpy())
    X["account_baseline"] = baseline
    categories = [canonical_name(code) for code in X["primary_cat_code"].to_numpy(dtype=int)]

    print(
        f"Train stats: global_mean={stats['global_train_mean']:.4f}, "
        f"category medians for {len(stats['category_train_medians'])} categories (train-only)"
    )

    y_train = y[:train_end]
    y_val = y[train_end:validation_end]
    baseline_train = baseline[:train_end]
    baseline_val = baseline[train_end:validation_end]
    residual_train = y_train - baseline_train
    residual_val = y_val - baseline_val

    validation_frame = frame.iloc[train_end:validation_end].reset_index(drop=True)
    validation_frame["primary_cat_code"] = X.iloc[train_end:validation_end]["primary_cat_code"].to_numpy(dtype=int)

    legacy_X = build_legacy_m5_frame(X, frame, categories)

    objective, alpha = config["objective"], config["alpha"]
    precision_alpha = alpha if objective == "quantile" else 0.5

    ablation_features: dict[str, pd.DataFrame | None] = {
        "A0": None,
        "A1": None,
        "A2": X[A2_FEATURES],
        "A3": X[A3_FEATURES],
        "A4": legacy_X,
    }
    ablation_targets = {
        "A0": "category_baseline",
        "A1": "account_offset",
        "A2": "residual",
        "A3": "residual",
        "A4": "residual",
    }

    category_prediction = _category_baseline(
        X["primary_cat_code"].to_numpy(dtype=int), service.category_train_medians, service.default_popularity
    )

    print("Training ablation ladder (validation-selected, test untouched)...")
    ablation_results: dict[str, dict] = {}
    fitted_models: dict[str, object] = {}
    for code, features in ablation_features.items():
        if code == "A0":
            predictions_val = category_prediction[train_end:validation_end]
            metrics = base_potential_metrics(y_val, predictions_val, alpha=precision_alpha)
            ablation_results[code] = {
                "description": "category/global baseline only",
                "feature_count": 0,
                "target": ablation_targets[code],
                "validation": metrics,
                "subgroups": subgroup_metrics(validation_frame, y_val, predictions_val, alpha=precision_alpha),
            }
            print(f"[{code}] validation MAE={metrics['mae']:.4f} pinball={metrics['pinball_loss']:.4f}")
            continue
        if code == "A1":
            predictions_val = baseline_val
            metrics = base_potential_metrics(y_val, predictions_val, alpha=precision_alpha)
            ablation_results[code] = {
                "description": "account offset only (shrunk user history prior)",
                "feature_count": 1,
                "target": ablation_targets[code],
                "validation": metrics,
                "subgroups": subgroup_metrics(validation_frame, y_val, predictions_val, alpha=precision_alpha),
            }
            print(f"[{code}] validation MAE={metrics['mae']:.4f} pinball={metrics['pinball_loss']:.4f}")
            continue

        model = fit_base_model(
            features.iloc[:train_end],
            residual_train,
            features.iloc[train_end:validation_end],
            residual_val,
            objective=objective,
            alpha=alpha,
            params=config["lgbm_params"],
        )
        predictions_val = baseline_val + model.predict(features.iloc[train_end:validation_end])
        metrics = base_potential_metrics(y_val, predictions_val, alpha=precision_alpha)
        ablation_results[code] = {
            "description": {
                "A2": "account offset + content (category/tag/text/history/context)",
                "A3": "A2 + media type",
                "A4": "legacy M5 vector (time features + baseline as input)",
            }[code],
            "feature_count": int(features.shape[1]),
            "target": ablation_targets[code],
            "validation": metrics,
            "subgroups": subgroup_metrics(validation_frame, y_val, predictions_val, alpha=precision_alpha),
            "best_iteration": int(getattr(model, "best_iteration_", 0) or 0),
        }
        fitted_models[code] = model
        print(
            f"[{code}] validation MAE={metrics['mae']:.4f} pinball={metrics['pinball_loss']:.4f} "
            f"rho={metrics['spearman']:.4f} features={features.shape[1]}"
        )

    production_code = min(
        PRODUCTION_CANDIDATES,
        key=lambda code: (
            ablation_results[code]["validation"]["pinball_loss"],
            ablation_results[code]["validation"]["mae"],
        ),
    )
    print(f"Selected production variant: {production_code} (validation pinball + MAE tie-break)")

    production_model = fitted_models[production_code]
    MODEL_OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    production_model.booster_.save_model(str(MODEL_OUTPUT))

    production_features = A2_FEATURES if production_code == "A2" else A3_FEATURES
    feature_importance = sorted(
        (
            {"feature": feature, "importance": int(importance)}
            for feature, importance in zip(production_features, production_model.feature_importances_)
        ),
        key=lambda entry: entry["importance"],
        reverse=True,
    )

    quality_report = {}
    if DATA_QUALITY_REPORT.exists():
        quality_report = json.loads(DATA_QUALITY_REPORT.read_text(encoding="utf-8"))

    dataset_sha256 = quality_report.get("raw_file_sha256")
    payload = {
        "model_kind": "base_potential_lgbm (Layer A, no time features)",
        "production_variant": production_code,
        "objective": {"name": objective, "alpha": alpha if objective == "quantile" else None},
        "hyperparameters": config["lgbm_params"],
        "feature_contract": {
            "production_features": production_features,
            "a2_features": A2_FEATURES,
            "a3_features": A3_FEATURES,
            "time_features_present": False,
            "note": (
                "hour/weekday/month/cyclical encodings/cat_x_hour/cat_x_weekday/history_x_hour are "
                "absent from the model; account_baseline is the residual offset, not an input."
            ),
        },
        "split": bounds.to_dict(frame),
        "global_train_mean": stats["global_train_mean"],
        "category_train_medians": stats["category_train_medians"],
        "ablations": ablation_results,
        "selection_rule": (
            f"validation pinball loss first, validation MAE as tie-break, candidates {PRODUCTION_CANDIDATES}; "
            "test split not read in this script"
        ),
        "feature_importance": feature_importance,
        "base_potential": ablation_results[production_code]["validation"],
        "base_potential_subgroups": ablation_results[production_code]["subgroups"],
        "dataset": {
            "rows": int(len(frame)),
            "raw_file_sha256": dataset_sha256,
            "valid_row_count": quality_report.get("valid_row_count"),
            "demo_row_count": quality_report.get("demo_row_count"),
            "timezone_basis_distribution": quality_report.get("timezone_basis_distribution"),
        },
        "tuning_source": config["source"],
        "elapsed_seconds": round(time.time() - started, 2),
    }
    provenance = {
        "git_commit": git_commit_sha(),
        "git_dirty": git_code_is_dirty(),
        "git_worktree_dirty": git_is_dirty(),
        "trained_at_utc": utc_now_iso(),
        "dataset_parquet": str(PARQUET_FILE),
        "dataset_sha256": file_sha256(PARQUET_FILE),
        "raw_file_sha256": dataset_sha256,
        "model_output": str(MODEL_OUTPUT),
        "model_output_sha256": file_sha256(MODEL_OUTPUT),
        "split_protocol": "chronological_train_validation_locked_test",
        "tuning_data": "validation_only",
        "test_touched_before_final": False,
    }
    write_json_with_provenance(METRICS_OUTPUT, payload, provenance)

    print(f"Saved production model ({production_code}) to {MODEL_OUTPUT}")
    print(f"Validation metrics written to {METRICS_OUTPUT}")
    print(f"Elapsed: {payload['elapsed_seconds']}s")
    return payload


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--limit-rows",
        type=int,
        default=None,
        help="Smoke-test only: train on the first N chronological rows (never for real artifacts).",
    )
    return parser.parse_args(argv)


if __name__ == "__main__":
    arguments = _parse_args()
    train(limit_rows=arguments.limit_rows)

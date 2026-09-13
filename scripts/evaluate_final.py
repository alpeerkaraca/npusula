"""The single, locked evaluation of the untouched test split.

Run this **once**, after `tune_lgbm.py` has locked the configuration and
`05_train_lgbm.py` / `06_time_lift.py` have written the production artifacts.
It refuses to run when the upstream artifacts admit that the test split was read
during tuning.

It reports three separate things and never merges them into one number:
  B. base-potential metrics (post popularity prediction — MAE/Spearman live here),
  C. time-lift held-out observational metrics (window quality),
  D. the product confidence report (what users would actually see).

Output: artifacts/final_evaluation.json
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import time

import numpy as np
import pandas as pd

from backend.config import settings
from backend.services.canonical_taxonomy import canonical_name
from backend.services.legacy_m5_features import build_legacy_m5_frame
from backend.services.provenance import file_sha256, git_commit_sha, git_is_dirty, utc_now_iso, write_json_with_provenance
from backend.services.recommendation import A2_FEATURES, A3_FEATURES, RecommendationService
from backend.services.time_lift import TimeLiftConfig, TimeLiftTable
from backend.services.time_lift_eval import evaluate_windows
from backend.services.training import (
    add_bucket_column,
    base_potential_metrics,
    build_recommendation_service,
    compute_split_bounds,
    fit_base_model,
    fit_train_statistics,
    load_chronological_frame,
    subgroup_metrics,
)

PARQUET_FILE = Path("data/processed/posts.parquet")
METRICS_INPUT = Path("artifacts/base_potential_metrics.json")
TUNING_INPUT = Path("artifacts/tuning_results.json")
TIME_LIFT_INPUT = Path("artifacts/time_lift_table.json")
LEGACY_METRICS = Path("artifacts/legacy/metrics.json")
OUTPUT = Path("artifacts/final_evaluation.json")

FEATURE_SETS = {"A2": A2_FEATURES, "A3": A3_FEATURES}


def _assert_test_untouched() -> dict:
    """Refuses to produce a 'final' report from a protocol that already peeked."""
    if not TUNING_INPUT.exists():
        raise FileNotFoundError(f"{TUNING_INPUT} missing: tuning must run (validation-only) before the final run.")
    tuning = json.loads(TUNING_INPUT.read_text(encoding="utf-8"))
    protocol = tuning.get("protocol", {})
    if protocol.get("test_rows_loaded", 0) != 0:
        raise RuntimeError("Refusing to run: tune_lgbm.py recorded that it loaded test rows.")
    if tuning.get("provenance", {}).get("test_touched_before_final") is not False:
        raise RuntimeError("Refusing to run: tuning provenance does not certify the test split as untouched.")
    if METRICS_INPUT.exists():
        training = json.loads(METRICS_INPUT.read_text(encoding="utf-8"))
        if training.get("provenance", {}).get("test_touched_before_final") is not False:
            raise RuntimeError("Refusing to run: training provenance does not certify the test split as untouched.")
    return {"tuning_protocol": protocol, "checked_at": utc_now_iso()}


def _selected_validation_lift_metrics(tuning: dict, layer_config: TimeLiftConfig) -> dict | None:
    """The validation numbers of the selected Layer B config, for the test comparison."""
    selected_lift = tuning.get("selected", {}).get("time_lift", {})
    for entry in tuning.get("stage_2_lift_grid", []):
        if all(
            entry.get(key) == selected_lift.get(key)
            for key in ("bucket_hours", "shrinkage_k", "min_support_posts", "min_support_users", "min_meaningful_lift")
        ):
            return entry
    bucket_entry = next(
        (
            entry for entry in tuning.get("stage_2_bucket_size", [])
            if entry.get("bucket_hours") == layer_config.bucket_hours
        ),
        None,
    )
    return bucket_entry


def evaluate(limit_rows: int | None = None) -> dict:
    started = time.time()
    audit = _assert_test_untouched()
    tuning = json.loads(TUNING_INPUT.read_text(encoding="utf-8"))
    selected = tuning["selected"]
    layer_config = TimeLiftConfig(**selected["time_lift"])
    objective = selected["objective"]
    alpha = selected["alpha"]
    precision_alpha = alpha if alpha is not None else 0.5

    training_metrics = json.loads(METRICS_INPUT.read_text(encoding="utf-8"))
    production_variant = training_metrics.get("production_variant", "A3")
    production_features = FEATURE_SETS[production_variant]
    print(f"Production variant: {production_variant} ({len(production_features)} features)")

    frame = load_chronological_frame(PARQUET_FILE)
    if limit_rows:
        frame = frame.iloc[:limit_rows].reset_index(drop=True)
        print(f"[smoke mode] limited to {len(frame):,} rows")
    frame = add_bucket_column(frame, layer_config.bucket_hours)
    bounds = compute_split_bounds(len(frame))
    y = pd.to_numeric(frame["popularity_score"], errors="coerce").fillna(5.8).to_numpy(dtype=float)

    # The service is re-hydrated with the *persisted* train-only statistics so
    # cold-start medians cannot be recomputed from the test window by accident.
    service = build_recommendation_service(default_popularity=float(training_metrics["global_train_mean"]))
    # Point the service at the production model; the statistics above stay the
    # ones the training script persisted (never recomputed from test rows).
    service.model_path = settings.MODEL_PATH
    service.category_train_medians = {
        int(code): float(value) for code, value in training_metrics["category_train_medians"].items()
    }
    svd_path = Path("artifacts/text_svd_model.joblib")
    if svd_path.exists():
        import joblib

        service.svd_pipeline = joblib.load(svd_path)
    # Load the production booster itself: the locked artifact, never a refit.
    if not service.model_path.exists():
        raise FileNotFoundError(f"production model missing at {service.model_path}")
    service.model = RecommendationService._load_booster_crlf_safe(service.model_path)
    if service.model.num_feature() != len(production_features):
        raise RuntimeError(
            f"production model expects {service.model.num_feature()} features, "
            f"but variant {production_variant} declares {len(production_features)}"
        )

    X = service._prepare_features(frame)
    baseline = service.account_baseline(frame, categories=X["primary_cat_code"].to_numpy())
    categories = [canonical_name(code) for code in X["primary_cat_code"].to_numpy(dtype=int)]

    test_slice = slice(bounds.validation_end, bounds.n_rows)
    y_test = y[test_slice]
    test_frame = frame.iloc[test_slice].reset_index(drop=True).copy()
    test_frame["primary_cat_code"] = X.iloc[test_slice]["primary_cat_code"].to_numpy(dtype=int)

    residual_predictions = service.model.predict(X.iloc[test_slice][production_features])
    test_predictions = baseline[test_slice] + residual_predictions

    print("B — base-potential metrics on the locked test split")
    base_metrics = base_potential_metrics(y_test, test_predictions, alpha=precision_alpha)
    base_subgroups = subgroup_metrics(test_frame, y_test, test_predictions, alpha=precision_alpha)
    baseline_offset_metrics = base_potential_metrics(y_test, baseline[test_slice], alpha=precision_alpha)
    print(
        f"  MAE={base_metrics['mae']:.4f} median_AE={base_metrics['median_ae']:.4f} "
        f"rho={base_metrics['spearman']:.4f} pinball={base_metrics['pinball_loss']:.4f} "
        f"bias={base_metrics['prediction_bias']:+.4f}"
    )

    print("C — time-lift held-out observational metrics")
    if not TIME_LIFT_INPUT.exists():
        raise FileNotFoundError(f"{TIME_LIFT_INPUT} missing: run scripts/06_time_lift.py first.")
    table = TimeLiftTable.load(TIME_LIFT_INPUT)
    test_frame["category_code"] = X.iloc[test_slice]["primary_cat_code"].to_numpy(dtype=int)
    test_frame["bucket"] = test_frame["time_bucket"].astype(int)
    test_frame["residual"] = y_test - test_predictions
    test_frame["cold_start"] = test_frame["user_post_count_prior"].to_numpy(dtype=int) == 0
    test_frame["timezone_fallback"] = test_frame["timezone_basis"].astype(str).to_numpy() == "utc_fallback"
    lift_metrics = evaluate_windows(table, test_frame, test_predictions, layer_config)
    print(
        f"  ndcg@3={lift_metrics['ndcg_at_3']} lift_MAE={lift_metrics['held_out_bucket_lift_mae']:.4f} "
        f"tie_rate={lift_metrics['tie_or_no_claim_rate']:.3f} supported={lift_metrics['supported_bucket_count']}"
    )

    print("Same-protocol legacy comparison (A4 = legacy M5 vector, retrained here)")
    X["account_baseline"] = baseline  # the legacy vector takes the offset as an input
    legacy_X = build_legacy_m5_frame(X, frame, categories)
    legacy_model = fit_base_model(
        legacy_X.iloc[: bounds.train_end],
        y[: bounds.train_end] - baseline[: bounds.train_end],
        legacy_X.iloc[bounds.train_end:bounds.validation_end],
        y[bounds.train_end:bounds.validation_end] - baseline[bounds.train_end:bounds.validation_end],
        objective=objective,
        alpha=alpha if alpha is not None else 0.55,
        params=selected["lgbm_params"],
    )
    legacy_predictions = baseline[test_slice] + legacy_model.predict(legacy_X.iloc[test_slice])
    legacy_metrics = base_potential_metrics(y_test, legacy_predictions, alpha=precision_alpha)
    print(f"  legacy MAE={legacy_metrics['mae']:.4f} rho={legacy_metrics['spearman']:.4f}")

    # Diagnostic, not a production candidate: the same legacy vector *without*
    # the offset as an input. It separates "time features carry post-level
    # signal" from "the offset was double-counted as an input".
    legacy_no_baseline_columns = [
        column for column in legacy_X.columns
        if column not in {"account_baseline", "history_x_hour"}
    ]
    legacy_no_baseline = fit_base_model(
        legacy_X.iloc[: bounds.train_end][legacy_no_baseline_columns],
        y[: bounds.train_end] - baseline[: bounds.train_end],
        legacy_X.iloc[bounds.train_end:bounds.validation_end][legacy_no_baseline_columns],
        y[bounds.train_end:bounds.validation_end] - baseline[bounds.train_end:bounds.validation_end],
        objective=objective,
        alpha=alpha if alpha is not None else 0.55,
        params=selected["lgbm_params"],
    )
    legacy_no_baseline_predictions = baseline[test_slice] + legacy_no_baseline.predict(
        legacy_X.iloc[test_slice][legacy_no_baseline_columns]
    )
    legacy_no_baseline_metrics = base_potential_metrics(
        y_test, legacy_no_baseline_predictions, alpha=precision_alpha
    )
    print(
        f"  legacy without baseline-as-input MAE={legacy_no_baseline_metrics['mae']:.4f} "
        f"rho={legacy_no_baseline_metrics['spearman']:.4f}"
    )

    historical_legacy = None
    if LEGACY_METRICS.exists():
        document = json.loads(LEGACY_METRICS.read_text(encoding="utf-8"))
        historical_legacy = {
            "note": (
                "Archived number from the pre-rework artifact. NOT comparable: different split protocol, "
                "and the same test split had already been inspected during tuning."
            ),
            "stored_model_mae": document.get("model_mae"),
            "stored_model_spearman": document.get("model_spearman"),
            "stored_baseline_mae": document.get("baseline_mae"),
            "stored_dataset_rows": document.get("dataset_rows"),
        }

    # D — product confidence report
    total_test = len(test_frame)
    cold_start_rate = float(test_frame["cold_start"].mean())
    tz_fallback_rate = float(test_frame["timezone_fallback"].mean())
    product_report = {
        "test_rows": int(total_test),
        "confidence_rate": lift_metrics["confidence_rate"],
        "cold_start_recommendation_rate": round(cold_start_rate, 6),
        "utc_fallback_recommendation_rate": round(tz_fallback_rate, 6),
        "no_claim_or_broad_window_rate": lift_metrics["tie_or_no_claim_rate"],
        "positive_lift_precision_by_confidence": lift_metrics["positive_lift_precision_by_confidence"],
    }

    payload = {
        "split_protocol": "chronological_train_validation_locked_test",
        "tuning_data": "validation_only",
        "test_touched_before_final": False,
        "evaluation_run_count": 1,
        "split": bounds.to_dict(frame),
        "dataset": {
            "rows": int(len(frame)),
            "parquet_sha256": file_sha256(PARQUET_FILE),
            "raw_file_sha256": training_metrics.get("dataset", {}).get("raw_file_sha256"),
            "demo_row_count": training_metrics.get("dataset", {}).get("demo_row_count"),
            "timezone_basis_distribution": training_metrics.get("dataset", {}).get("timezone_basis_distribution"),
        },
        "production_variant": production_variant,
        "objective": {"name": objective, "alpha": alpha},
        "base_potential": {
            **base_metrics,
            "baseline_mae": baseline_offset_metrics["mae"],
            "baseline_spearman": baseline_offset_metrics["spearman"],
            "baseline_kind": "account_baseline (shrunk user history prior, train-only category medians)",
        },
        "base_potential_subgroups": base_subgroups,
        "time_lift": {
            **lift_metrics,
            "interpretation": (
                "Held-out observational generalisation of the window ranking. Not causal: the Flickr "
                "corpus is observational and has no randomised exploration."
            ),
        },
        "product_confidence_report": product_report,
        "legacy_comparison": {
            "protocol": "same train/validation/test split, same residual target, legacy 36-column vector",
            "metrics": legacy_metrics,
            "diagnostic_without_baseline_input": {
                "metrics": legacy_no_baseline_metrics,
                "note": (
                    "Same legacy vector with `account_baseline` removed as an input (it stays the "
                    "residual offset). Separates the time features' contribution from the "
                    "double-counted offset. Not a production candidate either."
                ),
            },
            "interpretation": (
                "The legacy vector scores lower post-level MAE because it is allowed to condition "
                "on the publish hour — the very variable the product has to choose — and to take "
                "`account_baseline` as an input while it is also the residual offset. Neither is "
                "available in the recommendation task, so this is a same-protocol reference, not "
                "a better recommender."
            ),
            "historical_artifact": historical_legacy,
        },
        "feature_importance": training_metrics.get("feature_importance", []),
        "time_lift_validation_reference": _selected_validation_lift_metrics(tuning, layer_config),
        "metric_interpretation": {
            "mae": "Post popularity prediction error only. Not window/timing quality.",
            "spearman": "Post popularity ranking quality only. Not window/timing quality.",
            "pinball_loss": "Quantile loss of the base-potential prediction.",
            "time_lift_ndcg_at_3": "Observational ranking quality of the 3-hour windows (held out).",
            "time_lift_hit_rates": "Observational; only rows whose group passed the support bar are scored.",
            "mean_recommended_lift_delta_vs_baseline": (
                "Recommended window minus an arbitrary supported window of the same category/weekday. "
                "The absolute recommended lift is expected to be negative on held-out data because "
                "groups are selected by their train estimate (winner's curse); only this delta is "
                "readable."
            ),
            "bootstrap_ci_coverage": (
                "Share of group intervals containing the held-out mean. Below the nominal level means "
                "the intervals are too narrow under temporal drift — reported, not hidden."
            ),
            "legacy_advantage": (
                "The legacy vector's lower post-level MAE comes from conditioning on the publish hour "
                "and from using the residual offset as an input. Neither is available when the hour is "
                "the decision variable."
            ),
            "causality": (
                "No causal claim is made anywhere. A causal statement requires EnSosyal A/B or controlled "
                "exploration data."
            ),
        },
        "audit": audit,
        "elapsed_seconds": round(time.time() - started, 2),
    }
    provenance = {
        "git_commit": git_commit_sha(),
        "git_dirty": git_is_dirty(),
        "evaluated_at_utc": utc_now_iso(),
        "dataset_sha256": file_sha256(PARQUET_FILE),
        "model_path": str(service.model_path),
        "time_lift_path": str(TIME_LIFT_INPUT),
        "split_protocol": "chronological_train_validation_locked_test",
        "tuning_data": "validation_only",
        "test_touched_before_final": False,
    }
    write_json_with_provenance(OUTPUT, payload, provenance)
    print(f"Final evaluation written to {OUTPUT} ({payload['elapsed_seconds']}s)")
    return payload


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit-rows", type=int, default=None, help="Smoke-test only.")
    return parser.parse_args(argv)


if __name__ == "__main__":
    arguments = _parse_args()
    evaluate(limit_rows=arguments.limit_rows)

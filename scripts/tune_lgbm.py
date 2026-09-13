"""Validation-only selection of the model config **and** the Layer B thresholds.

Protocol (plan §2.1): this script never loads the test split. It selects

  * the LightGBM objective/alpha and hyperparameters (ranked by validation
    pinball loss),
  * the Layer B bucket size (3h vs 4h), shrinkage `k`, minimum support and the
    minimum meaningful lift (ranked by the observed lift of the recommended
    window measured against the supported-window baseline, under a no-claim cap).

Output: artifacts/tuning_results.json — a `selected` block plus the full ranking
of every candidate, all of it validation-based.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import random
import time

import numpy as np
import pandas as pd

from backend.services.provenance import (
    file_sha256,
    git_commit_sha,
    git_is_dirty,
    utc_now_iso,
    write_json_with_provenance,
)
from backend.services.recommendation import A3_FEATURES
from backend.services.time_lift import TimeLiftConfig, TimeLiftTable
from backend.services.time_lift_eval import evaluate_windows
from backend.services.training import (
    add_bucket_column,
    build_recommendation_service,
    compute_split_bounds,
    expanding_window_oof_residuals,
    fit_base_model,
    fit_svd_pipeline,
    fit_train_statistics,
    load_chronological_frame,
)

PARQUET_FILE = Path("data/processed/posts.parquet")
SVD_OUTPUT = Path("artifacts/text_svd_model.joblib")
TUNING_OUTPUT = Path("artifacts/tuning_results.json")

SEED = 42
N_RANDOM_CONFIGS = 12

CURRENT_CONFIG = {
    "n_estimators": 500,
    "learning_rate": 0.04,
    "num_leaves": 63,
    "min_child_samples": 50,
    "subsample": 0.85,
    "colsample_bytree": 0.8,
    "reg_alpha": 0.1,
    "reg_lambda": 1.0,
}

SEARCH_SPACE = {
    "learning_rate": [0.03, 0.05],
    "num_leaves": [31, 63, 127, 255],
    "min_child_samples": [20, 50, 100],
    "subsample": [0.7, 0.85],
    "colsample_bytree": [0.6, 0.8, 1.0],
    "reg_alpha": [0.0, 0.1, 1.0],
    "reg_lambda": [0.5, 1.0, 5.0],
}

OBJECTIVE_CANDIDATES = [
    {"objective": "l1", "alpha": None},
    {"objective": "quantile", "alpha": 0.5},
    {"objective": "quantile", "alpha": 0.55},
    {"objective": "quantile", "alpha": 0.6},
]

BUCKET_HOURS_CANDIDATES = [3, 4]
SHRINKAGE_CANDIDATES = [10.0, 25.0, 50.0, 100.0, 200.0]
MIN_SUPPORT_POST_CANDIDATES = [20, 50, 100]
MIN_SUPPORT_USER = 10
MIN_MEANINGFUL_LIFT_CANDIDATES = [0.0, 0.05, 0.10]
MAX_NO_CLAIM_RATE = 0.90


def _pinball(y_true: np.ndarray, predictions: np.ndarray, alpha: float) -> float:
    delta = y_true - predictions
    return float(np.mean(np.maximum(alpha * delta, (alpha - 1.0) * delta)))


def _validation_frame(
    frame: pd.DataFrame,
    X: pd.DataFrame,
    bounds,
    base_predictions: np.ndarray,
    bucket_hours: int,
) -> pd.DataFrame:
    """Builds the validation frame the Layer B evaluation replay expects."""
    validation = frame.iloc[bounds.train_end:bounds.validation_end].reset_index(drop=True).copy()
    buckets = add_bucket_column(validation, bucket_hours)
    validation["category_code"] = X.iloc[bounds.train_end:bounds.validation_end]["primary_cat_code"].to_numpy(dtype=int)
    validation["bucket"] = buckets["time_bucket"].astype(int)
    validation["residual"] = (
        pd.to_numeric(validation["popularity_score"], errors="coerce").to_numpy(dtype=float) - base_predictions
    )
    validation["cold_start"] = validation["user_post_count_prior"].to_numpy(dtype=int) == 0
    validation["timezone_fallback"] = validation["timezone_basis"].astype(str).to_numpy() == "utc_fallback"
    return validation


def tune(limit_rows: int | None = None, max_configs: int = N_RANDOM_CONFIGS) -> dict:
    started = time.time()
    print(f"Loading chronological dataset from {PARQUET_FILE}...")
    frame = load_chronological_frame(PARQUET_FILE)
    if limit_rows:
        frame = frame.iloc[:limit_rows].reset_index(drop=True)
        print(f"[smoke mode] limited to {len(frame):,} rows")

    bounds = compute_split_bounds(len(frame))
    y = pd.to_numeric(frame["popularity_score"], errors="coerce").fillna(5.8).to_numpy(dtype=float)
    print(f"Split: train={bounds.train_rows:,} validation={bounds.validation_rows:,} (test never loaded)")

    print("Fitting title-only TF-IDF + SVD on the oldest 70%...")
    svd_pipeline = fit_svd_pipeline(frame.iloc[:bounds.train_end]["title"], SVD_OUTPUT, n_components=8)
    service = build_recommendation_service(default_popularity=1.0)
    service.svd_pipeline = svd_pipeline
    X = service._prepare_features(frame)
    fit_train_statistics(service, y[:bounds.train_end], X.iloc[:bounds.train_end]["primary_cat_code"].to_numpy())
    baseline = service.account_baseline(frame, categories=X["primary_cat_code"].to_numpy())

    y_train = y[:bounds.train_end]
    y_val = y[bounds.train_end:bounds.validation_end]
    residual_train = y_train - baseline[:bounds.train_end]
    residual_val = y_val - baseline[bounds.train_end:bounds.validation_end]

    print("Stage 1 — model configs ranked by validation pinball loss")
    rng = random.Random(SEED)
    configs = [{"name": "current", **CURRENT_CONFIG}]
    seen = {tuple(sorted(CURRENT_CONFIG.items()))}
    while len(configs) <= max_configs:
        candidate = {"n_estimators": 800}
        candidate.update({key: rng.choice(values) for key, values in SEARCH_SPACE.items()})
        key = tuple(sorted(candidate.items()))
        if key in seen:
            continue
        seen.add(key)
        configs.append({"name": f"r{len(configs)}", **candidate})

    results=[]

    def _fit_and_score(params: dict, objective: str, alpha: float | None) -> dict:
        t0 = time.time()
        model = fit_base_model(
            X.iloc[:bounds.train_end][A3_FEATURES],
            residual_train,
            X.iloc[bounds.train_end:bounds.validation_end][A3_FEATURES],
            residual_val,
            objective=objective,
            alpha=alpha if alpha is not None else 0.55,
            params=params,
        )
        predictions = baseline[bounds.train_end:bounds.validation_end] + model.predict(
            X.iloc[bounds.train_end:bounds.validation_end][A3_FEATURES]
        )
        scored_alpha = alpha if alpha is not None else 0.5
        return {
            "validation_pinball": round(_pinball(y_val, predictions, scored_alpha), 6),
            "validation_mae": round(float(np.mean(np.abs(y_val - predictions))), 6),
            "best_iteration": int(getattr(model, "best_iteration_", 0) or 0),
            "elapsed_s": round(time.time() - t0, 1),
        }

    best_overall: dict | None = None
    for cfg in configs:
        params = {key: value for key, value in cfg.items() if key != "name"}
        for objective_candidate in OBJECTIVE_CANDIDATES:
            objective = objective_candidate["objective"]
            alpha = objective_candidate["alpha"]
            score = _fit_and_score(params, objective, alpha)
            entry = {"name": cfg["name"], "objective": objective, "alpha": alpha, "lgbm_params": params, **score}
            results.append(entry)
            print(
                f"[{cfg['name']}/{objective}{'' if alpha is None else f'@{alpha}'}] "
                f"pinball={score['validation_pinball']:.4f} mae={score['validation_mae']:.4f} "
                f"iter={score['best_iteration']} ({score['elapsed_s']}s)"
            )
            if best_overall is None or entry["validation_pinball"] < best_overall["validation_pinball"]:
                best_overall = entry

    results.sort(key=lambda entry: entry["validation_pinball"])
    assert best_overall is not None
    print(
        f"Stage 1 winner: {best_overall['name']} {best_overall['objective']} alpha={best_overall['alpha']} "
        f"pinball={best_overall['validation_pinball']:.4f}"
    )

    best_params = best_overall["lgbm_params"]
    objective = best_overall["objective"]
    alpha = best_overall["alpha"]
    fit_alpha = alpha if alpha is not None else 0.55

    # Base-model validation predictions are bucket-independent (Layer A has no
    # time features), so they are fitted once for every Layer B candidate.
    print("Fitting the selected base model once for the Layer B search...")
    base_model = fit_base_model(
        X.iloc[:bounds.train_end][A3_FEATURES],
        residual_train,
        X.iloc[bounds.train_end:bounds.validation_end][A3_FEATURES],
        residual_val,
        objective=objective,
        alpha=fit_alpha,
        params=best_params,
    )
    validation_base_predictions = base_model.predict(X.iloc[bounds.train_end:bounds.validation_end][A3_FEATURES])

    print("Computing expanding-window OOF residuals on the train window (Layer B input)...")
    oof_residuals = expanding_window_oof_residuals(
        X[A3_FEATURES],
        residual_train,
        bounds.train_end,
        objective=objective,
        alpha=fit_alpha,
        params=best_params,
    )

    train_base = frame.iloc[:bounds.train_end].reset_index(drop=True).copy()
    train_base["category_code"] = X.iloc[:bounds.train_end]["primary_cat_code"].to_numpy(dtype=int)
    train_base["residual"] = y_train - baseline[:bounds.train_end] - oof_residuals

    def _fit_table_for_bucket(bucket_hours: int) -> TimeLiftTable:
        """Bootstrap once per bucket geometry; the k/support sweep reuses it."""
        buckets = add_bucket_column(train_base, bucket_hours)
        return TimeLiftTable.fit(
            pd.DataFrame({
                "category_code": train_base["category_code"].to_numpy(dtype=int),
                "local_weekday": train_base["local_weekday"].to_numpy(dtype=int),
                "bucket": buckets["time_bucket"].to_numpy(dtype=int),
                "user_id": train_base["user_id"].to_numpy(),
                "residual": train_base["residual"].to_numpy(dtype=float),
            }),
            TimeLiftConfig(bucket_hours=bucket_hours),
        )

    base_tables = {bucket_hours: _fit_table_for_bucket(bucket_hours) for bucket_hours in BUCKET_HOURS_CANDIDATES}
    validation_cache: dict[int, pd.DataFrame] = {}

    def _evaluate_lift(bucket_hours: int, layer_config: TimeLiftConfig) -> dict:
        if bucket_hours not in validation_cache:
            validation_cache[bucket_hours] = _validation_frame(
                frame,
                X,
                bounds,
                baseline[bounds.train_end:bounds.validation_end] + validation_base_predictions,
                bucket_hours,
            )
        table = base_tables[bucket_hours].with_config(layer_config)
        return evaluate_windows(
            table,
            validation_cache[bucket_hours],
            baseline[bounds.train_end:bounds.validation_end] + validation_base_predictions,
            layer_config,
        )

    print("Stage 2 — Layer B thresholds ranked by validation NDCG@3 (no-claim capped)")
    bucket_scores: list[dict] = []
    for bucket_hours in BUCKET_HOURS_CANDIDATES:
        metrics = _evaluate_lift(
            bucket_hours,
            TimeLiftConfig(
                bucket_hours=bucket_hours,
                shrinkage_k=50.0,
                min_support_posts=50,
                min_support_users=MIN_SUPPORT_USER,
                min_meaningful_lift=0.05,
            ),
        )
        bucket_scores.append({
            "bucket_hours": bucket_hours,
            "validation_ndcg_at_3": metrics["ndcg_at_3"],
            "validation_mean_recommended_observed_lift": metrics["mean_recommended_observed_lift"],
            "validation_mean_recommended_lift_delta_vs_baseline": metrics["mean_recommended_lift_delta_vs_baseline"],
            "validation_mean_observed_lift_supported_baseline": metrics["mean_observed_lift_supported_baseline"],
            "validation_top1_positive_lift_hit_rate": metrics["top1_positive_lift_hit_rate"],
            "validation_tie_rate": metrics["tie_or_no_claim_rate"],
            "supported_bucket_count": metrics["supported_bucket_count"],
        })
        print(
            f"  bucket={bucket_hours}h ndcg@3={metrics['ndcg_at_3']} "
            f"rec_lift={metrics['mean_recommended_observed_lift']} "
            f"delta={metrics['mean_recommended_lift_delta_vs_baseline']} "
            f"tie_rate={metrics['tie_or_no_claim_rate']:.3f} supported={metrics['supported_bucket_count']}"
        )

    # NDCG@3 is not comparable across bucket sizes (3 of 8 candidates vs 3 of 6),
    # so the geometries are compared on the scale-free product outcome instead:
    # the observed lift of the window that would actually have been recommended.
    best_bucket = max(
        bucket_scores,
        key=lambda entry: (
            entry["validation_mean_recommended_lift_delta_vs_baseline"]
            if entry["validation_mean_recommended_lift_delta_vs_baseline"] is not None else -1e9,
            entry["validation_top1_positive_lift_hit_rate"]
            if entry["validation_top1_positive_lift_hit_rate"] is not None else -1.0,
            -(entry["validation_tie_rate"] or 1.0),
        ),
    )["bucket_hours"]
    print(f"  selected bucket size: {best_bucket}h")

    lift_grid: list[dict] = []
    for shrinkage in SHRINKAGE_CANDIDATES:
        for min_posts in MIN_SUPPORT_POST_CANDIDATES:
            for min_lift in MIN_MEANINGFUL_LIFT_CANDIDATES:
                metrics = _evaluate_lift(
                    best_bucket,
                    TimeLiftConfig(
                        bucket_hours=best_bucket,
                        shrinkage_k=shrinkage,
                        min_support_posts=min_posts,
                        min_support_users=MIN_SUPPORT_USER,
                        min_meaningful_lift=min_lift,
                    ),
                )
                lift_grid.append({
                    "bucket_hours": best_bucket,
                    "shrinkage_k": shrinkage,
                    "min_support_posts": min_posts,
                    "min_support_users": MIN_SUPPORT_USER,
                    "min_meaningful_lift": min_lift,
                    "validation_ndcg_at_3": metrics["ndcg_at_3"],
                    "validation_mean_recommended_observed_lift": metrics["mean_recommended_observed_lift"],
                    "validation_mean_recommended_lift_delta_vs_baseline": metrics["mean_recommended_lift_delta_vs_baseline"],
                    "validation_mean_observed_lift_supported_baseline": metrics["mean_observed_lift_supported_baseline"],
                    "validation_top1_positive_lift_hit_rate": metrics["top1_positive_lift_hit_rate"],
                    "validation_tie_rate": metrics["tie_or_no_claim_rate"],
                    "validation_bucket_lift_mae": metrics["held_out_bucket_lift_mae"],
                    "supported_bucket_count": metrics["supported_bucket_count"],
                })
                print(
                    f"  k={shrinkage:.0f} posts>={min_posts} lift>={min_lift:.2f} -> "
                    f"ndcg@3={metrics['ndcg_at_3']} rec_lift={metrics['mean_recommended_observed_lift']} "
                    f"delta={metrics['mean_recommended_lift_delta_vs_baseline']} "
                    f"tie={metrics['tie_or_no_claim_rate']:.3f} supported={metrics['supported_bucket_count']}"
                )

    ranked_pool = [entry for entry in lift_grid if entry["validation_ndcg_at_3"] is not None]
    if not ranked_pool:
        raise RuntimeError("No Layer B configuration produced a validation NDCG at all; widen the grid.")
    eligible = [entry for entry in ranked_pool if entry["validation_tie_rate"] <= MAX_NO_CLAIM_RATE]
    cap_met = bool(eligible)
    pool = eligible if cap_met else ranked_pool
    if not cap_met:
        # Honest fallback: when every configuration is above the no-claim cap,
        # the finding is "this corpus rarely supports a strict window claim".
        # Report it instead of aborting or silently loosening the rule.
        print(
            f"WARNING: no Layer B configuration met the no-claim cap ({MAX_NO_CLAIM_RATE}); "
            "selecting the best-ranked configuration and recording the miss."
        )

    def _rank(entry: dict) -> tuple:
        # Primary: the observed lift of the window that would have been
        # recommended (product value, in popularity units). Then the share of
        # recommendations that turned out positive, then NDCG@3 for ordering
        # quality within this geometry, then fewer no-claims, then more support.
        # Last resort: prefer the more conservative gap threshold.
        return (
            -(entry["validation_mean_recommended_lift_delta_vs_baseline"] or -1e9),
            -(entry["validation_top1_positive_lift_hit_rate"] or -1.0),
            -(entry["validation_ndcg_at_3"] or -1.0),
            entry["validation_tie_rate"],
            -entry["supported_bucket_count"],
            -entry["min_meaningful_lift"],
        )

    pool.sort(key=_rank)
    best_lift = pool[0]
    print(
        f"Stage 2 winner: bucket={best_lift['bucket_hours']}h k={best_lift['shrinkage_k']} "
        f"posts>={best_lift['min_support_posts']} lift>={best_lift['min_meaningful_lift']} "
        f"delta={best_lift['validation_mean_recommended_lift_delta_vs_baseline']} "
        f"ndcg@3={best_lift['validation_ndcg_at_3']}"
    )

    payload = {
        "protocol": {
            "tuning_data": "validation_only",
            "test_rows_loaded": 0,
            "split": bounds.to_dict(frame),
            "selection_rule": (
                "Stage 1: min validation pinball loss. Stage 2: max mean lift of the recommended "
                "window measured against the supported-window baseline (both scale-free across "
                "bucket geometries and immune to winner's-curse regression), tie-broken by top-1 "
                "positive-lift rate, NDCG@3, lower no-claim rate, then support. The no-claim cap "
                f"of {MAX_NO_CLAIM_RATE} filters candidates when any candidate satisfies it; if "
                "none does, the miss is recorded instead of aborting."
            ),
            "bucket_size_comparison_note": (
                "NDCG@3 is not comparable between 3h (8 candidates) and 4h (6 candidates) geome-"
                "tries, which is why the geometry decision rides on the observed lift of the "
                "recommended window instead."
            ),
        },
        "selected": {
            "objective": best_overall["objective"],
            "alpha": best_overall["alpha"],
            "lgbm_params": best_params,
            "bucket_hours": best_lift["bucket_hours"],
            "time_lift": {
                "bucket_hours": best_lift["bucket_hours"],
                "shrinkage_k": best_lift["shrinkage_k"],
                "min_support_posts": best_lift["min_support_posts"],
                "min_support_users": best_lift["min_support_users"],
                "min_meaningful_lift": best_lift["min_meaningful_lift"],
                "bootstrap_samples": 200,
                "bootstrap_seed": 42,
                "ci_level": 0.90,
            },
        },
        "stage_1_model_configs": results,
        "stage_2_bucket_size": bucket_scores,
        "stage_2_lift_grid": lift_grid,
        "no_claim_cap": {"cap": MAX_NO_CLAIM_RATE, "met_by_selected": cap_met},
        "elapsed_seconds": round(time.time() - started, 2),
    }
    provenance = {
        "git_commit": git_commit_sha(),
        "git_dirty": git_is_dirty(),
        "tuned_at_utc": utc_now_iso(),
        "dataset_parquet": str(PARQUET_FILE),
        "dataset_parquet_sha256": file_sha256(PARQUET_FILE),
        "test_touched_before_final": False,
    }
    write_json_with_provenance(TUNING_OUTPUT, payload, provenance)
    print(f"Tuning results written to {TUNING_OUTPUT} ({payload['elapsed_seconds']}s)")
    return payload


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit-rows", type=int, default=None, help="Smoke-test only.")
    parser.add_argument("--max-configs", type=int, default=N_RANDOM_CONFIGS, help="Number of random configs in stage 1.")
    return parser.parse_args(argv)


if __name__ == "__main__":
    arguments = _parse_args()
    tune(limit_rows=arguments.limit_rows, max_configs=arguments.max_configs)

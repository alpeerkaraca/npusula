"""Chronological LightGBM ablation training for the residual recommendation model."""
from __future__ import annotations

import json
from pathlib import Path
import time

import joblib
import lightgbm as lgb
import numpy as np
import pandas as pd
from scipy.stats import spearmanr
from sklearn.decomposition import TruncatedSVD
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics import mean_absolute_error
from sklearn.pipeline import Pipeline

from backend.services.history_feature import compute_leakage_free_history
from backend.services.recommendation import (
    CATEGORY_FEATURES,
    CONTEXT_FEATURES,
    FEATURE_COLUMNS,
    MEDIA_FEATURES,
    TAG_FEATURES,
    TEXT_SVD_FEATURES,
    TIME_FEATURES,
    RecommendationService,
)

PARQUET_FILE = Path("data/processed/posts.parquet")
MODEL_OUTPUT = Path("artifacts/lgbm_popularity.txt")
METRICS_OUTPUT = Path("artifacts/metrics.json")
SVD_OUTPUT = Path("artifacts/text_svd_model.joblib")

M1_FEATURES = TIME_FEATURES
M2_FEATURES = TIME_FEATURES + CATEGORY_FEATURES + ["cat_x_hour", "cat_x_weekday"]
M3_FEATURES = M2_FEATURES + TAG_FEATURES
M4_FEATURES = M3_FEATURES + CONTEXT_FEATURES + TEXT_SVD_FEATURES + MEDIA_FEATURES
# Every variant is trained on the RESIDUAL target (y - account_baseline) so the
# table isolates incremental feature contributions. M0 is the formulation
# reference: full feature set on the RAW target, showing what the residual
# formulation itself buys over the feature engineering.
ABLATION_FEATURES = {
    "M0": FEATURE_COLUMNS,
    "M1": M1_FEATURES,
    "M2": M2_FEATURES,
    "M3": M3_FEATURES,
    "M4": M4_FEATURES,
    "M5": FEATURE_COLUMNS,
}


def _spearman(y_true: np.ndarray, predictions: np.ndarray) -> float:
    if len(y_true) < 2 or np.all(predictions == predictions[0]):
        return 0.0
    value = spearmanr(y_true, predictions).statistic
    return 0.0 if not np.isfinite(value) else float(value)


def _metrics(y_true: np.ndarray, predictions: np.ndarray) -> dict[str, float]:
    return {
        "mae": round(float(mean_absolute_error(y_true, predictions)), 6),
        "spearman": round(_spearman(y_true, predictions), 6),
    }


def _fit_model(
    X_train: pd.DataFrame,
    y_train: np.ndarray,
    X_val: pd.DataFrame,
    y_val: np.ndarray,
) -> lgb.LGBMRegressor:
    model = lgb.LGBMRegressor(
        objective="regression_l1",
        n_estimators=500,
        learning_rate=0.04,
        num_leaves=63,
        min_child_samples=50,
        subsample=0.85,
        colsample_bytree=0.8,
        reg_alpha=0.1,
        reg_lambda=1.0,
        random_state=42,
        n_jobs=-1,
        verbosity=-1,
    )
    model.fit(
        X_train,
        y_train,
        eval_set=[(X_val, y_val)],
        callbacks=[lgb.early_stopping(50, verbose=False)],
    )
    return model


def _subgroup_metrics(
    features: pd.DataFrame,
    y_true: np.ndarray,
    predictions: np.ndarray,
) -> dict[str, dict[str, float | int]]:
    groups: dict[str, dict[str, float | int]] = {}

    def record(name: str, mask: np.ndarray) -> None:
        count = int(mask.sum())
        if count:
            groups[name] = {"count": count, **_metrics(y_true[mask], predictions[mask])}

    names = ["cold_start", "very_low_history", "low_history", "medium_history", "high_history"]
    for code, name in enumerate(names):
        record(f"history_depth:{name}", features["history_depth_code"].to_numpy() == code)
    record("time_basis:local", features["time_basis_utc_fallback"].to_numpy() == 0)
    record("time_basis:utc_fallback", features["time_basis_utc_fallback"].to_numpy() == 1)
    for code in sorted(features["primary_cat_code"].astype(int).unique()):
        record(f"primary_cat_code:{code}", features["primary_cat_code"].to_numpy() == code)
    return groups


def train() -> None:
    started = time.time()
    print(f"Loading chronological dataset from {PARQUET_FILE}...")
    df = pd.read_parquet(PARQUET_FILE)
    df["published_at_utc"] = pd.to_datetime(df["published_at_utc"], utc=True)
    df = df.sort_values("published_at_utc").reset_index(drop=True)
    target_column = "target_popularity" if "target_popularity" in df.columns else "popularity_score"
    y = pd.to_numeric(df[target_column], errors="coerce").fillna(5.8).to_numpy(dtype=float)

    n_rows = len(df)
    train_end = int(n_rows * 0.70)
    val_end = int(n_rows * 0.85)
    if train_end == 0 or val_end <= train_end or val_end >= n_rows:
        raise ValueError("Dataset is too small for a 70/15/15 chronological split.")

    global_mean = float(np.mean(y[:train_end]))
    global_median = float(np.median(y[:train_end]))
    # Recompute priors from chronologically preceding rows; never trust stale columns.
    df = compute_leakage_free_history(df, default_popularity_mean=global_mean)
    df = df.sort_values("published_at_utc").reset_index(drop=True)
    y = pd.to_numeric(df[target_column], errors="coerce").fillna(global_mean).to_numpy(dtype=float)

    print("Fitting title-only TF-IDF + SVD on the oldest 70%...")
    train_titles = df.iloc[:train_end]["title"].fillna("").astype(str)
    svd_pipeline = Pipeline([
        ("tfidf", TfidfVectorizer(max_features=5000, sublinear_tf=True)),
        ("svd", TruncatedSVD(n_components=len(TEXT_SVD_FEATURES), random_state=42)),
    ])
    svd_pipeline.fit(train_titles)
    SVD_OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(svd_pipeline, SVD_OUTPUT)

    rec_service = RecommendationService(model_path=Path("artifacts/.training-placeholder.txt"))
    rec_service.default_popularity = global_mean
    rec_service.svd_pipeline = svd_pipeline
    X = rec_service._prepare_features(df)
    if list(X.columns) != FEATURE_COLUMNS or X.shape[1] != 36:
        raise RuntimeError(f"Feature contract mismatch: expected 36 columns, got {X.shape[1]}.")

    # Cold-start fallback uses only category medians learned from the train window.
    train_codes = X.iloc[:train_end]["primary_cat_code"].astype(int).reset_index(drop=True)
    category_medians = pd.Series(y[:train_end]).groupby(train_codes).median()
    cold_mask = df["user_post_count_prior"].to_numpy() == 0
    cold_codes = X.loc[cold_mask, "primary_cat_code"].astype(int)
    X.loc[cold_mask, "account_baseline"] = cold_codes.map(category_medians).fillna(global_mean).to_numpy()

    test_slice = slice(val_end, n_rows)
    y_test = y[test_slice]
    results: dict[str, dict[str, float | int]] = {
        "B0": {"feature_count": 0, **_metrics(y_test, np.full(len(y_test), global_median))},
        "B1": {"feature_count": 1, **_metrics(y_test, X.iloc[test_slice]["account_baseline"].to_numpy())},
    }

    trained_models: dict[str, lgb.LGBMRegressor] = {}
    for code, columns in ABLATION_FEATURES.items():
        print(f"Training {code} with {len(columns)} features...")
        residual = code != "M0"
        baseline = X.iloc[:train_end]["account_baseline"].to_numpy()
        train_target = y[:train_end] - baseline if residual else y[:train_end]
        val_baseline = X.iloc[train_end:val_end]["account_baseline"].to_numpy()
        val_target = y[train_end:val_end] - val_baseline if residual else y[train_end:val_end]
        model = _fit_model(
            X.iloc[:train_end][columns], train_target,
            X.iloc[train_end:val_end][columns], val_target,
        )
        raw_predictions = model.predict(X.iloc[test_slice][columns])
        predictions = X.iloc[test_slice]["account_baseline"].to_numpy() + raw_predictions if residual else raw_predictions
        results[code] = {
            "feature_count": len(columns),
            "target": "residual" if residual else "ham",
            **_metrics(y_test, predictions),
        }
        trained_models[code] = model

    final_model = trained_models["M5"]
    final_predictions = X.iloc[test_slice]["account_baseline"].to_numpy() + final_model.predict(
        X.iloc[test_slice][FEATURE_COLUMNS]
    )
    feature_importance = sorted(
        ({"feature": f, "importance": int(i)} for f, i in zip(FEATURE_COLUMNS, final_model.feature_importances_)),
        key=lambda item: item["importance"], reverse=True,
    )
    MODEL_OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    final_model.booster_.save_model(str(MODEL_OUTPUT))

    metrics = {
        "dataset_rows": n_rows,
        "feature_count": len(FEATURE_COLUMNS),
        "target": target_column,
        "split": {
            "strategy": "chronological_70_15_15",
            "train_rows": train_end,
            "validation_rows": val_end - train_end,
            "test_rows": n_rows - val_end,
            "train_end_utc": df.iloc[train_end - 1]["published_at_utc"].isoformat(),
            "validation_end_utc": df.iloc[val_end - 1]["published_at_utc"].isoformat(),
        },
        "global_train_mean": global_mean,
        "global_train_median": global_median,
        "category_train_medians": {
            str(int(code)): float(value) for code, value in category_medians.items()
        },
        "ablations": results,
        "baseline_mae": results["B1"]["mae"],
        "baseline_spearman": results["B1"]["spearman"],
        "model_mae": results["M5"]["mae"],
        "model_spearman": results["M5"]["spearman"],
        "subgroups": _subgroup_metrics(X.iloc[test_slice], y_test, final_predictions),
        "feature_importance": feature_importance,
        "elapsed_seconds": round(time.time() - started, 2),
    }
    METRICS_OUTPUT.write_text(json.dumps(metrics, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(results, indent=2))
    print(f"Saved M5 residual model to {MODEL_OUTPUT} and metrics to {METRICS_OUTPUT}.")


if __name__ == "__main__":
    train()

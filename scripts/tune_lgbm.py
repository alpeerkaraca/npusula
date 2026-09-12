"""Random hyperparameter search for the residual LightGBM popularity model.

Uses the exact same chronological 70/15/15 split and feature pipeline as
05_train_lgbm.py (leakage-free history, title SVD, 36-feature contract).
Evaluates the test split overall plus the weak subgroups identified from
metrics.json (very_low_history, high_history, social_lifestyle cat 10,
technology cat 0) so a config that improves the average without crushing
a subgroup can be chosen.

Output: artifacts/tuning_results.json (all configs, ranked by test MAE).
"""
from __future__ import annotations

import json
import random
import time
from pathlib import Path

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
    FEATURE_COLUMNS,
    RecommendationService,
    TEXT_SVD_FEATURES,
)

PARQUET_FILE = Path("data/processed/posts.parquet")
SVD_OUTPUT = Path("artifacts/text_svd_model.joblib")
TUNING_OUTPUT = Path("artifacts/tuning_results.json")
SEED = 42
N_RANDOM_CONFIGS = 24

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

# Weak subgroups to track (from metrics.json analysis, excluding cold_start)
TRACKED_SUBGROUPS = [
    ("very_low_history", lambda f: f["history_depth_code"].to_numpy() == 1),
    ("high_history", lambda f: f["history_depth_code"].to_numpy() == 4),
    ("cat10_social_lifestyle", lambda f: f["primary_cat_code"].to_numpy() == 10),
    ("cat0_technology", lambda f: f["primary_cat_code"].to_numpy() == 0),
    ("cold_start_watch", lambda f: f["history_depth_code"].to_numpy() == 0),
]


def _spearman(y_true: np.ndarray, predictions: np.ndarray) -> float:
    if len(y_true) < 2 or np.all(predictions == predictions[0]):
        return 0.0
    value = spearmanr(y_true, predictions).statistic
    return 0.0 if not np.isfinite(value) else float(value)


def _score(y_true: np.ndarray, predictions: np.ndarray, features: pd.DataFrame) -> dict:
    result = {
        "mae": round(float(mean_absolute_error(y_true, predictions)), 6),
        "spearman": round(_spearman(y_true, predictions), 6),
    }
    for name, mask_fn in TRACKED_SUBGROUPS:
        mask = mask_fn(features)
        if mask.sum():
            result[name] = {
                "count": int(mask.sum()),
                "mae": round(float(mean_absolute_error(y_true[mask], predictions[mask])), 6),
                "spearman": round(_spearman(y_true[mask], predictions[mask]), 6),
            }
    return result


def _fit_and_predict(
    config: dict,
    X_train: pd.DataFrame,
    y_train: np.ndarray,
    X_val: pd.DataFrame,
    y_val: np.ndarray,
    X_test: pd.DataFrame,
) -> np.ndarray:
    model = lgb.LGBMRegressor(
        objective="regression_l1",
        random_state=SEED,
        n_jobs=-1,
        verbosity=-1,
        **config,
    )
    model.fit(
        X_train, y_train,
        eval_set=[(X_val, y_val)],
        callbacks=[lgb.early_stopping(50, verbose=False)],
    )
    return model.predict(X_test), model.best_iteration_


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
    global_mean = float(np.mean(y[:train_end]))
    df = compute_leakage_free_history(df, default_popularity_mean=global_mean)
    df = df.sort_values("published_at_utc").reset_index(drop=True)
    y = pd.to_numeric(df[target_column], errors="coerce").fillna(global_mean).to_numpy(dtype=float)

    print("Fitting title TF-IDF + SVD on the oldest 70%...")
    svd_pipeline = Pipeline([
        ("tfidf", TfidfVectorizer(max_features=5000, sublinear_tf=True)),
        ("svd", TruncatedSVD(n_components=len(TEXT_SVD_FEATURES), random_state=SEED)),
    ])
    svd_pipeline.fit(df.iloc[:train_end]["title"].fillna("").astype(str))
    SVD_OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(svd_pipeline, SVD_OUTPUT)

    rec_service = RecommendationService(model_path=Path("artifacts/.training-placeholder.txt"))
    rec_service.default_popularity = global_mean
    rec_service.svd_pipeline = svd_pipeline
    X = rec_service._prepare_features(df)
    if list(X.columns) != FEATURE_COLUMNS or X.shape[1] != 36:
        raise RuntimeError(f"Feature contract mismatch: expected 36 columns, got {X.shape[1]}.")

    train_codes = X.iloc[:train_end]["primary_cat_code"].astype(int).reset_index(drop=True)
    category_medians = pd.Series(y[:train_end]).groupby(train_codes).median()
    cold_mask = df["user_post_count_prior"].to_numpy() == 0
    cold_codes = X.loc[cold_mask, "primary_cat_code"].astype(int)
    X.loc[cold_mask, "account_baseline"] = cold_codes.map(category_medians).fillna(global_mean).to_numpy()

    baseline = X["account_baseline"].to_numpy()
    y_train_res = y[:train_end] - baseline[:train_end]
    y_val_res = y[train_end:val_end] - baseline[train_end:val_end]
    y_test = y[val_end:]
    X_train, X_val = X.iloc[:train_end], X.iloc[train_end:val_end]
    X_test = X.iloc[val_end:]
    test_features = X_test.reset_index(drop=True)

    print(f"Prepared splits: train={len(X_train)}, val={len(X_val)}, test={len(X_test)}")

    rng = random.Random(SEED)
    configs = [{"name": "current", **CURRENT_CONFIG}]
    seen = {tuple(sorted(CURRENT_CONFIG.items()))}
    while len(configs) <= N_RANDOM_CONFIGS:
        candidate = {"n_estimators": 800}
        candidate.update({key: rng.choice(values) for key, values in SEARCH_SPACE.items()})
        key = tuple(sorted(candidate.items()))
        if key in seen:
            continue
        seen.add(key)
        configs.append({"name": f"r{len(configs)}", **candidate})

    results = []
    for cfg in configs:
        name = cfg.pop("name")
        t0 = time.time()
        raw_predictions, best_iter = _fit_and_predict(cfg, X_train, y_train_res, X_val, y_val_res, X_test)
        predictions = baseline[val_end:] + raw_predictions
        score = _score(y_test, predictions, test_features)
        elapsed = round(time.time() - t0, 1)
        results.append({"config": cfg, "best_iteration": best_iter, "elapsed_s": elapsed, **score})
        print(f"[{name}] MAE={score['mae']:.4f} rho={score['spearman']:.4f} "
              f"iter={best_iter} ({elapsed}s) {cfg}")

    results.sort(key=lambda r: r["mae"])
    TUNING_OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    TUNING_OUTPUT.write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")

    print("\n=== top 5 by test MAE ===")
    for r in results[:5]:
        subs = " ".join(
            f"{k.split('_')[0]}={v['mae']:.3f}" for k, v in r.items()
            if k in {s[0] for s in TRACKED_SUBGROUPS}
        )
        print(f"MAE={r['mae']:.4f} rho={r['spearman']:.4f} | {subs}")
        print(f"   {r['config']}")

    print(f"Total elapsed: {time.time() - started:.1f}s")


if __name__ == "__main__":
    train()

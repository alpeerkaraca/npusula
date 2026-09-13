"""Leakage tests for the two-layer pipeline (plan §2.2).

Each test states the leak it forbids and then tries to cause it.
"""
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from sklearn.feature_extraction.text import TfidfVectorizer

from backend.services.history_feature import compute_leakage_free_history
from backend.services.recommendation import A3_FEATURES
from backend.services.training import (
    build_recommendation_service,
    compute_split_bounds,
    fit_svd_pipeline,
    fit_train_statistics,
    load_chronological_frame,
)


def _frame(rows: list[dict]) -> pd.DataFrame:
    return pd.DataFrame(rows)


def test_expanding_window_history_never_sees_the_current_post():
    """Kept from the original suite: the current target must not enter its own prior."""
    now = datetime.now(timezone.utc)
    frame = _frame([
        {"user_id": "u1", "published_at_utc": now - timedelta(days=3), "popularity_score": 6.0},
        {"user_id": "u1", "published_at_utc": now - timedelta(days=2), "popularity_score": 8.0},
        {"user_id": "u1", "published_at_utc": now - timedelta(days=1), "popularity_score": 10.0},
    ])

    result = compute_leakage_free_history(frame, default_popularity_mean=5.0)

    assert result.loc[0, "user_post_count_prior"] == 0
    assert result.loc[0, "user_popularity_mean_prior"] == 5.0
    assert result.loc[1, "user_popularity_mean_prior"] == 6.0
    assert result.loc[2, "user_popularity_mean_prior"] == 7.0


def test_changing_the_current_post_leaves_its_own_prior_untouched_and_moves_followers():
    """Only *later* posts of the same user may see a changed score."""
    now = datetime.now(timezone.utc)
    base_rows = [
        {"user_id": "u1", "published_at_utc": now - timedelta(days=3), "popularity_score": 6.0},
        {"user_id": "u1", "published_at_utc": now - timedelta(days=2), "popularity_score": 8.0},
        {"user_id": "u1", "published_at_utc": now - timedelta(days=1), "popularity_score": 10.0},
    ]
    baseline = compute_leakage_free_history(_frame(base_rows), default_popularity_mean=5.0)

    edited_rows = [dict(row) for row in base_rows]
    edited_rows[1]["popularity_score"] = 16.0  # only post #1 changes
    edited = compute_leakage_free_history(_frame(edited_rows), default_popularity_mean=5.0)

    # Post #1's own prior is unchanged...
    assert edited.loc[1, "user_post_count_prior"] == baseline.loc[1, "user_post_count_prior"] == 1
    assert edited.loc[1, "user_popularity_mean_prior"] == baseline.loc[1, "user_popularity_mean_prior"] == 6.0
    # ...and the earlier post is unaffected too.
    assert edited.loc[0, "user_popularity_mean_prior"] == baseline.loc[0, "user_popularity_mean_prior"] == 5.0
    # Only the later post's prior moves: (6 + 16) / 2 = 11
    assert edited.loc[2, "user_popularity_mean_prior"] == 11.0
    assert baseline.loc[2, "user_popularity_mean_prior"] == 7.0


def test_future_same_user_post_cannot_change_past_features():
    """Appending a future post must leave every earlier *post* unchanged.

    The comparison is by post_id: the history computation re-sorts rows
    chronologically, so row positions are not stable identifiers.
    """
    now = datetime.now(timezone.utc)
    rows = [
        {"post_id": "a", "user_id": "u1", "published_at_utc": now - timedelta(days=5), "popularity_score": 6.0},
        {"post_id": "b", "user_id": "u1", "published_at_utc": now - timedelta(days=4), "popularity_score": 7.0},
        {"post_id": "c", "user_id": "u2", "published_at_utc": now - timedelta(days=3), "popularity_score": 9.0},
    ]
    before = compute_leakage_free_history(_frame(rows), default_popularity_mean=5.0).set_index("post_id")

    with_future = rows + [
        {"post_id": "z", "user_id": "u1", "published_at_utc": now - timedelta(hours=1), "popularity_score": 19.0},
    ]
    after = compute_leakage_free_history(_frame(with_future), default_popularity_mean=5.0).set_index("post_id")

    for post_id in ("a", "b", "c"):
        assert after.loc[post_id, "user_post_count_prior"] == before.loc[post_id, "user_post_count_prior"]
        assert (
            after.loc[post_id, "user_popularity_mean_prior"]
            == before.loc[post_id, "user_popularity_mean_prior"]
        )
    # The future post itself does see the earlier ones: (6 + 7) / 2 = 6.5
    assert after.loc["z", "user_popularity_mean_prior"] == 6.5


@pytest.fixture(scope="module")
def parquet_frame():
    path = Path("data/processed/posts.parquet")
    if not path.exists():
        pytest.skip("data/processed/posts.parquet not available in this checkout")
    return load_chronological_frame(path)


def test_train_only_category_medians_ignore_validation_and_test(parquet_frame):
    """"Category medians are computed from the train window only."""
    frame = parquet_frame.iloc[:60_000].reset_index(drop=True)
    bounds = compute_split_bounds(len(frame))
    y = frame["popularity_score"].to_numpy(dtype=float)

    service = build_recommendation_service(default_popularity=1.0)
    X = service._prepare_features(frame)
    codes = X["primary_cat_code"].to_numpy()

    fit_train_statistics(service, y[: bounds.train_end], codes[: bounds.train_end])

    train_only = pd.Series(y[: bounds.train_end]).groupby(pd.Series(codes[: bounds.train_end].astype(int))).median()
    all_window = pd.Series(y).groupby(pd.Series(codes.astype(int))).median()

    # The fitted medians must equal a train-only recomputation exactly...
    for code, value in service.category_train_medians.items():
        assert value == pytest.approx(float(train_only[code]))

    # ...and differ from the all-window medians at least once, otherwise this
    # test could not detect the leak it guards against.
    assert any(
        abs(float(train_only[code]) - float(all_window[code])) > 1e-6
        for code in service.category_train_medians
    )


def test_text_vocabulary_is_fitted_on_train_only(parquet_frame, tmp_path):
    """TF-IDF/SVD vocabulary must not learn validation or test titles."""
    frame = parquet_frame.iloc[:20_000].reset_index(drop=True)
    bounds = compute_split_bounds(len(frame))
    horizon_titles = frame.iloc[bounds.train_end:]["title"].fillna("").astype(str)

    svd_path = tmp_path / "svd.joblib"
    pipeline = fit_svd_pipeline(frame.iloc[: bounds.train_end]["title"], svd_path, n_components=4)
    vectorizer: TfidfVectorizer = pipeline.named_steps["tfidf"]

    train_tokens = set(vectorizer.get_feature_names_out())
    assert train_tokens, "the fitted vocabulary is empty; the check below would be vacuous"

    # A token that only exists after the train window must be out-of-vocabulary:
    # if the vectorizer had been fitted on the horizon, it would be in there.
    horizon_tokens = set()
    for title in horizon_titles.head(200):
        horizon_tokens.update(token for token in title.lower().split() if len(token) > 4)
    unseen = horizon_tokens - train_tokens
    assert unseen, "horizon shares every token with train; pick a different slice for this check"

    # Vocabulary indices can never exceed the fitted vocabulary size.
    assert vectorizer.transform(horizon_titles.head(5)).shape[1] == len(train_tokens)


def test_feature_matrix_has_no_time_columns(parquet_frame):
    """Layer A must not see hour/weekday/month or their interactions."""
    frame = parquet_frame.iloc[:5_000].reset_index(drop=True)
    service = build_recommendation_service(default_popularity=6.0)
    X = service._prepare_features(frame)

    forbidden = {
        "hour", "weekday", "month", "hour_sin", "hour_cos", "weekday_sin", "weekday_cos",
        "is_weekend", "cat_x_hour", "cat_x_weekday", "history_x_hour", "local_hour",
        "local_weekday", "time_bucket",
    }
    assert forbidden & set(X.columns) == set()
    assert list(X.columns) == A3_FEATURES


def test_account_baseline_is_the_offset_not_an_input(parquet_frame):
    """`account_baseline` must be usable as the residual offset but never as an input."""
    frame = parquet_frame.iloc[:5_000].reset_index(drop=True)
    service = build_recommendation_service(default_popularity=6.0)
    X = service._prepare_features(frame)
    baseline = service.account_baseline(frame, categories=X["primary_cat_code"].to_numpy())

    assert "account_baseline" not in X.columns
    assert "user_popularity_mean_prior" not in X.columns
    assert baseline.shape[0] == len(frame)
    # Cold-start rows fall back to the global mean when no medians are known yet.
    cold = frame["user_post_count_prior"].to_numpy() == 0
    if cold.any() and not service.category_train_medians:
        assert np.allclose(baseline[cold], service.default_popularity)

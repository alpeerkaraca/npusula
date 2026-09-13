"""Feature-engineering contract and candidate generation."""
from datetime import datetime, timezone

import pandas as pd

from backend.services.candidate_generator import (
    build_candidate_windows,
    extract_time_features,
)
from backend.services.history_feature import compute_leakage_free_history
from backend.services.recommendation import (
    A2_FEATURES,
    A3_FEATURES,
    BASE_FEATURES,
    RecommendationService,
)


def test_leakage_free_history_calculation():
    """Verify that prior mean and count never include the current or future post scores."""
    now = datetime.now(timezone.utc)
    df = pd.DataFrame([
        {"user_id": "u1", "published_at_utc": now - pd.Timedelta(days=3), "popularity_score": 6.0},
        {"user_id": "u1", "published_at_utc": now - pd.Timedelta(days=2), "popularity_score": 8.0},
        {"user_id": "u1", "published_at_utc": now - pd.Timedelta(days=1), "popularity_score": 10.0},
    ])

    result = compute_leakage_free_history(df, default_popularity_mean=5.0)

    assert result.loc[0, "user_post_count_prior"] == 0
    assert result.loc[0, "user_popularity_mean_prior"] == 5.0
    assert result.loc[1, "user_post_count_prior"] == 1
    assert result.loc[1, "user_popularity_mean_prior"] == 6.0
    assert result.loc[2, "user_post_count_prior"] == 2
    assert result.loc[2, "user_popularity_mean_prior"] == 7.0


def test_build_candidate_windows_covers_the_local_horizon():
    """7 days x 8 three-hour buckets, generated in local time."""
    start = datetime(2026, 9, 14, 10, 0, tzinfo=timezone.utc)
    windows = build_candidate_windows(start, days_ahead=7)

    assert len(windows) == 7 * 8
    assert {window.bucket for window in windows} == set(range(8))
    for window in windows:
        assert window.local_start.minute == 0
        assert window.local_start.hour in {0, 3, 6, 9, 12, 15, 18, 21}
        assert window.local_end - window.local_start == pd.Timedelta(hours=3)


def test_build_candidate_windows_rejects_naive_datetimes():
    import pytest

    with pytest.raises(ValueError):
        build_candidate_windows(datetime(2026, 9, 14, 10, 0))


def test_extract_time_features_is_reporting_only():
    dt = datetime(2026, 9, 12, 12, 0, 0, tzinfo=timezone.utc)  # Saturday
    features = extract_time_features(dt)
    assert features["hour"] == 12.0
    assert features["is_weekend"] == 1.0
    assert "hour_sin" in features and "hour_cos" in features


def test_extract_concept_features():
    from backend.services.tag_taxonomy import extract_concept_features, get_dominant_concept

    tags = ["eyeliner", "lipstick", "mascara", "coding"]
    concepts = extract_concept_features(tags)

    assert concepts["concept_beauty_cosmetics"] > 0
    assert concepts["concept_tech_software"] > 0
    assert concepts["concept_gaming_esports"] == 0.0

    dom_cat, dom_idx = get_dominant_concept(concepts)
    assert dom_cat == "beauty_cosmetics"
    assert 0 <= dom_idx <= 11


def test_clean_and_filter_tags_drops_noise_but_keeps_known_tags():
    from backend.services.tag_taxonomy import clean_and_filter_tags

    raw_tags = ["#Canon", "nikon", "2024", "eyeliner", "iphone", "software", "porn"]
    clean_tags, noise_ratio = clean_and_filter_tags(raw_tags)

    assert "eyeliner" in clean_tags
    assert "software" in clean_tags
    for noise in ("canon", "nikon", "2024", "porn", "iphone"):
        assert noise not in clean_tags
    assert round(noise_ratio, 2) == 0.71  # 5 of 7 are generic/NSFW/unknown


def test_base_feature_contract_has_no_time_features():
    """Layer A's contract: content + history only (plan §3.2)."""
    assert BASE_FEATURES == A3_FEATURES
    assert len(BASE_FEATURES) == 24
    assert set(A2_FEATURES) == set(A3_FEATURES) - {"media_type_code"}

    for forbidden in (
        "hour", "weekday", "month", "hour_sin", "hour_cos", "weekday_sin", "weekday_cos",
        "is_weekend", "cat_x_hour", "cat_x_weekday", "history_x_hour", "account_baseline",
        "user_followers", "user_popularity_mean_prior", "source_user_photo_count",
    ):
        assert forbidden not in BASE_FEATURES

    for expected in (
        "history_depth_code", "primary_cat_code", "primary_subcat_code", "primary_cat_confidence",
        "has_secondary_cat", "context_source_code", "media_type_code",
        "aligned_tag_count", "mismatched_tag_count", "unknown_tag_count",
        "generic_tag_count", "nsfw_tag_count", "semantic_tag_ratio", "unknown_tag_ratio",
        "tag_category_entropy", "timezone_basis_fallback",
    ):
        assert expected in BASE_FEATURES


def test_prepare_features_shape_and_dtypes():
    rec = RecommendationService()
    df = pd.DataFrame([{
        "user_popularity_mean_prior": 6.5,
        "user_post_count_prior": 10,
        "media_type": "video",
        "title": "Bilgisayar ve yapay zeka kodlama rehberi",
        "tags": ["#python", "#yazilim", "#canon"],
        "published_at_utc": datetime.now(timezone.utc),
        "timezone_basis": "source_offset",
        "category_l1": "Tech",
    }])

    X = rec._prepare_features(df)

    assert X.shape == (1, 24)
    assert list(X.columns) == BASE_FEATURES
    assert X["primary_cat_code"].iloc[0] == 0  # technology
    assert X["timezone_basis_fallback"].iloc[0] == 0.0
    assert X["media_type_code"].iloc[0] == 1.0
    assert X["aligned_tag_count"].iloc[0] >= 1.0
    assert X["unknown_tag_count"].iloc[0] >= 1.0  # "canon" is unknown, not "irrelevant"


def test_utc_fallback_flag_tracks_the_timezone_contract():
    rec = RecommendationService()
    frame = pd.DataFrame([
        {"title": "a", "tags": [], "user_post_count_prior": 1, "media_type": "photo",
         "timezone_basis": "utc_fallback"},
        {"title": "b", "tags": [], "user_post_count_prior": 1, "media_type": "photo",
         "timezone_basis": "source_offset"},
    ])

    X = rec._prepare_features(frame)

    assert X["timezone_basis_fallback"].tolist() == [1.0, 0.0]


def test_unknown_media_type_is_flagged_not_treated_as_photo():
    rec = RecommendationService()
    frame = pd.DataFrame([{
        "title": "x", "tags": [], "user_post_count_prior": 1,
        "media_type": "unknown", "timezone_basis": "source_offset",
    }])

    X = rec._prepare_features(frame)

    assert X["media_type_code"].iloc[0] == 2.0


def test_account_baseline_shrinks_towards_the_global_mean():
    from backend.services.recommendation import compute_account_baseline

    # No history -> global prior
    assert compute_account_baseline(0, 9.0, 6.0) == 6.0
    # Cold start with a category median -> category median
    assert compute_account_baseline(0, 9.0, 6.0, category_train_median=7.5) == 7.5
    # Shrunk mean sits between the user mean and the global mean
    shrunk = compute_account_baseline(10, 9.0, 6.0, alpha=10.0)
    assert 6.0 < shrunk < 9.0

"""Tests verifying the feature engineering pipeline and candidate generator."""
from datetime import datetime, timedelta, timezone
import numpy as np
import pandas as pd
import pytest

from backend.services.candidate_generator import (
    build_candidate_slots,
    extract_time_features,
    select_top_non_overlapping_slots,
)
from backend.services.history_feature import compute_leakage_free_history


def test_leakage_free_history_calculation():
    """Verify that prior mean and count never include the current or future post scores."""
    now = datetime.now(timezone.utc)
    df = pd.DataFrame([
        {"user_id": "u1", "published_at_utc": now - timedelta(days=3), "popularity_score": 6.0},
        {"user_id": "u1", "published_at_utc": now - timedelta(days=2), "popularity_score": 8.0},
        {"user_id": "u1", "published_at_utc": now - timedelta(days=1), "popularity_score": 10.0},
    ])

    result = compute_leakage_free_history(df, default_popularity_mean=5.0)

    # Post 0: Prior count = 0, Prior mean = default (5.0)
    assert result.loc[0, "user_post_count_prior"] == 0
    assert result.loc[0, "user_popularity_mean_prior"] == 5.0

    # Post 1: Prior count = 1, Prior mean = 6.0
    assert result.loc[1, "user_post_count_prior"] == 1
    assert result.loc[1, "user_popularity_mean_prior"] == 6.0

    # Post 2: Prior count = 2, Prior mean = (6.0 + 8.0)/2 = 7.0
    assert result.loc[2, "user_post_count_prior"] == 2
    assert result.loc[2, "user_popularity_mean_prior"] == 7.0


def test_build_candidate_slots_count_and_hours():
    """Verify candidate generator produces 28 slots at [9, 12, 18, 21]."""
    now = datetime(2026, 9, 12, 10, 0, 0, tzinfo=timezone.utc)
    slots = build_candidate_slots(start_time=now, days_ahead=7)
    assert len(slots) == 28

    # All slots should be at either 9, 12, 18, or 21
    valid_hours = {9, 12, 18, 21}
    for slot in slots:
        assert slot.hour in valid_hours
        assert slot.minute == 0


def test_extract_time_features():
    dt = datetime(2026, 9, 12, 12, 0, 0, tzinfo=timezone.utc)  # Saturday
    features = extract_time_features(dt)
    assert features["hour"] == 12.0
    assert features["is_weekend"] == 1.0
    assert "hour_sin" in features
    assert "hour_cos" in features
    assert "weekday_sin" in features
    assert "weekday_cos" in features


def test_select_top_non_overlapping_slots():
    """Verify selection enforces >= 3 hours gap between selected top-3 slots."""
    now = datetime(2026, 9, 12, 12, 0, 0, tzinfo=timezone.utc)
    candidates = [
        (now, 7.5),
        (now + timedelta(hours=1), 7.4),  # Too close to now (1 hour gap)
        (now + timedelta(hours=2), 7.3),  # Too close to now (2 hours gap)
        (now + timedelta(hours=4), 7.2),  # Valid gap (4 hours)
        (now + timedelta(hours=8), 7.0),  # Valid gap
    ]

    selected = select_top_non_overlapping_slots(candidates, top_k=3, min_gap_hours=3.0)
    assert len(selected) == 3
    assert selected[0].datetime_utc == now
    assert selected[0].predicted_popularity == 7.5
    assert selected[0].label == "Çok güçlü"

    # Second slot should skip the 1h and 2h slots and pick 4h slot
    assert selected[1].datetime_utc == now + timedelta(hours=4)
    assert selected[1].predicted_popularity == 7.2
    assert selected[1].label == "Güçlü"

    # Third slot should pick 8h slot
    assert selected[2].datetime_utc == now + timedelta(hours=8)
    assert selected[2].predicted_popularity == 7.0
    assert selected[2].label == "Orta"


def test_clean_and_filter_tags():
    from backend.services.tag_taxonomy import clean_and_filter_tags

    raw_tags = ["#Canon", "nikon", "2024", "eyeliner", "iphone", "software", "porn"]
    clean_tags, bl_ratio = clean_and_filter_tags(raw_tags)

    assert "eyeliner" in clean_tags
    assert "software" in clean_tags
    assert "canon" not in clean_tags
    assert "nikon" not in clean_tags
    assert "2024" not in clean_tags
    assert "porn" not in clean_tags
    assert "iphone" not in clean_tags
    # 5 out of 7 are blacklisted
    assert round(bl_ratio, 2) == 0.71


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


def test_recommendation_service_36_feature_contract():
    from backend.services.recommendation import RecommendationService, FEATURE_COLUMNS

    assert len(FEATURE_COLUMNS) == 36
    assert "account_baseline" in FEATURE_COLUMNS
    assert "history_depth_code" in FEATURE_COLUMNS
    assert "cat_x_hour" in FEATURE_COLUMNS
    assert "user_followers" not in FEATURE_COLUMNS
    assert "user_popularity_mean_prior" not in FEATURE_COLUMNS
    rec = RecommendationService()
    df = pd.DataFrame([{
        "user_popularity_mean_prior": 6.5,
        "user_post_count_prior": 10,
        "media_type": "video",
        "title": "Bilgisayar ve yapay zeka kodlama rehberi",
        "tags": ["#python", "#yazilim", "#canon"],
        "published_at_utc": datetime.now(timezone.utc),
    }])
    X = rec._prepare_features(df)
    assert X.shape[1] == 36
    for col in FEATURE_COLUMNS:
        assert col in X.columns

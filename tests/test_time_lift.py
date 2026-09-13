"""Layer B behaviour: train-only residuals, shrinkage, fallback, no-claim rule.

Covers plan §4.2-§4.4 and the §6.4 list (shrinkage, broad-window response,
cold-start confidence, local time in the API response).
"""
from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd
import pytest

from backend.services.time_lift import (
    CONFIDENCE_HIGH,
    CONFIDENCE_LOW,
    LEVEL_CATEGORY_BUCKET,
    LEVEL_CATEGORY_WEEKDAY_BUCKET,
    LEVEL_GLOBAL_BUCKET,
    LEVEL_GLOBAL_WEEKDAY_BUCKET,
    LEVEL_NEUTRAL,
    TimeLiftConfig,
    TimeLiftTable,
    WindowScore,
    decide_windows,
)
from backend.schemas.recommendation import RecommendedWindow
from backend.services.recommendation import RecommendationService


def _residual_frame(rows: list[tuple[int, int, int, str, float]]) -> pd.DataFrame:
    return pd.DataFrame(
        rows, columns=["category_code", "local_weekday", "bucket", "user_id", "residual"]
    )


def test_small_group_shrinks_towards_neutral():
    """A tiny group's reported lift must collapse towards zero (plan §4.2)."""
    config = TimeLiftConfig(shrinkage_k=100.0, min_support_posts=1, min_support_users=1, bootstrap_samples=50)
    rows = [
        (0, 0, 0, "u1", 4.0),
        (0, 0, 0, "u2", 2.0),
    ]
    table = TimeLiftTable.fit(_residual_frame(rows), config)
    entry = table.lookup(0, 0, 0)

    assert entry.raw_mean_lift == pytest.approx(3.0)
    assert entry.mean_lift == pytest.approx(3.0 * 2 / 102, abs=1e-6)
    assert abs(entry.mean_lift) < abs(entry.raw_mean_lift)


def test_large_group_keeps_most_of_its_lift():
    config = TimeLiftConfig(shrinkage_k=50.0, min_support_posts=1, min_support_users=1, bootstrap_samples=50)
    rows = [(0, 0, 0, f"u{index}", 1.0) for index in range(1000)]
    table = TimeLiftTable.fit(_residual_frame(rows), config)
    entry = table.lookup(0, 0, 0)

    assert entry.mean_lift == pytest.approx(1000 / 1050, abs=1e-6)


def test_hierarchy_falls_back_and_reports_the_level_it_used():
    """Sparse category x weekday x bucket must widen, and say so."""
    config = TimeLiftConfig(
        shrinkage_k=10.0, min_support_posts=100, min_support_users=10, bootstrap_samples=50
    )
    rows: list[tuple[int, int, int, str, float]] = []
    # Global bucket 6 has plenty of support...
    for index in range(400):
        rows.append((0, index % 7, 6, f"g{index}", 0.5))
    # ...category 3 x weekday 2 x bucket 6 has almost none.
    rows.append((3, 2, 6, "u1", 9.0))

    table = TimeLiftTable.fit(_residual_frame(rows), config)
    entry = table.lookup(3, 2, 6)

    assert entry.evidence_level in {LEVEL_GLOBAL_WEEKDAY_BUCKET, LEVEL_GLOBAL_BUCKET}
    # The tiny category-specific group must not have produced the number.
    assert entry.support_post_count >= 100
    assert entry.mean_lift < 1.0


def test_neutral_lift_when_no_group_meets_support():
    config = TimeLiftConfig(min_support_posts=10_000, min_support_users=10_000, bootstrap_samples=20)
    rows = [(0, 0, 0, "u1", 5.0)]
    table = TimeLiftTable.fit(_residual_frame(rows), config)
    entry = table.lookup(4, 5, 6)

    assert entry.evidence_level == LEVEL_NEUTRAL
    assert entry.mean_lift == 0.0
    assert entry.eligible is False


def test_bootstrap_interval_is_user_clustered_and_contains_the_mean():
    """Resampling is by user, so a single user with many posts cannot fake support."""
    config = TimeLiftConfig(shrinkage_k=1.0, min_support_posts=1, min_support_users=1, bootstrap_samples=200, ci_level=0.9)
    rows = [(0, 0, 0, "u1", 1.0) for _ in range(50)]  # one user, 50 posts
    table = TimeLiftTable.fit(_residual_frame(rows), config)
    entry = table.lookup(0, 0, 0)

    assert entry.support_post_count == 50
    assert entry.support_user_count == 1
    # With a single user the interval cannot be estimated: no fake precision.
    assert entry.ci_low is None and entry.ci_high is None

    many_users = [(0, 0, 0, f"u{index}", 1.0 + (index % 3) * 0.1) for index in range(60)]
    table_many = TimeLiftTable.fit(_residual_frame(many_users), config)
    entry_many = table_many.lookup(0, 0, 0)
    assert entry_many.ci_low is not None and entry_many.ci_high is not None
    assert entry_many.ci_low <= entry_many.mean_lift <= entry_many.ci_high


def test_lift_table_can_only_be_built_from_the_rows_it_is_given():
    """The fitted numbers must be a pure function of the residual frame."""
    config = TimeLiftConfig(shrinkage_k=10.0, min_support_posts=1, min_support_users=1, bootstrap_samples=30)
    train_rows = [(0, 1, 6, f"u{index}", 1.0) for index in range(50)]
    table_a = TimeLiftTable.fit(_residual_frame(train_rows), config)
    table_b = TimeLiftTable.fit(_residual_frame(train_rows), config)

    assert table_a.lookup(0, 1, 6).mean_lift == table_b.lookup(0, 1, 6).mean_lift
    assert table_a.coverage == table_b.coverage

    # A "test" row with an extreme residual must not move the train-fitted value.
    poisoned = train_rows + [(0, 1, 6, "future_user", 99.0)]
    table_c = TimeLiftTable.fit(_residual_frame(poisoned), config)
    assert table_c.lookup(0, 1, 6).support_post_count == 51  # it would count if it were passed
    assert table_a.lookup(0, 1, 6).support_post_count == 50  # but it was not


def test_with_config_reuses_bootstrap_and_validates_parameters():
    config = TimeLiftConfig(shrinkage_k=10.0, min_support_posts=1, min_support_users=1, bootstrap_samples=30)
    rows = [(0, 1, 6, f"u{index}", 1.0) for index in range(50)]
    table = TimeLiftTable.fit(_residual_frame(rows), config)

    tighter = table.with_config(
        TimeLiftConfig(shrinkage_k=1000.0, min_support_posts=1, min_support_users=1, bootstrap_samples=30)
    )
    assert tighter.lookup(0, 1, 6).mean_lift < table.lookup(0, 1, 6).mean_lift

    with pytest.raises(ValueError):
        table.with_config(
            TimeLiftConfig(shrinkage_k=10.0, min_support_posts=1, min_support_users=1, bootstrap_samples=99)
        )


def test_artifact_round_trip(tmp_path):
    config = TimeLiftConfig(shrinkage_k=10.0, min_support_posts=1, min_support_users=1, bootstrap_samples=30)
    rows = [(0, 1, 6, f"u{index}", 1.0) for index in range(50)]
    table = TimeLiftTable.fit(_residual_frame(rows), config)
    path = tmp_path / "time_lift.json"
    table.save(path, provenance={"note": "test"})

    loaded = TimeLiftTable.load(path)
    assert loaded.config.shrinkage_k == config.shrinkage_k
    assert loaded.lookup(0, 1, 6).mean_lift == table.lookup(0, 1, 6).mean_lift
    assert loaded.lookup(0, 1, 6).support_user_count == 50


def _window(bucket: int, lift: float, ci_low: float | None, eligible: bool = True) -> WindowScore:
    return WindowScore(
        weekday=1,
        bucket=bucket,
        lift=lift,
        evidence_level=LEVEL_CATEGORY_WEEKDAY_BUCKET,
        support_post_count=500,
        support_user_count=80,
        ci_low=ci_low,
        ci_high=None if ci_low is None else ci_low + 0.3,
        eligible=eligible,
    )


def test_decide_windows_claims_high_confidence_only_with_support_ci_and_gap():
    config = TimeLiftConfig(min_meaningful_lift=0.05)
    windows = [_window(6, 0.40, 0.10), _window(7, 0.10, -0.05), _window(5, 0.05, -0.1)]

    selected = decide_windows(7.0, windows, config, cold_start=False, timezone_fallback=False)

    assert selected[0].bucket == 6
    assert selected[0].confidence == CONFIDENCE_HIGH
    assert selected[0].is_tie_or_broad_window is False
    assert selected[0].score == pytest.approx(7.40)


def test_decide_windows_flags_a_broad_window_when_the_gap_is_small():
    config = TimeLiftConfig(min_meaningful_lift=0.05)
    windows = [_window(6, 0.20, 0.05), _window(7, 0.18, 0.03), _window(5, 0.01, -0.2)]

    selected = decide_windows(7.0, windows, config, cold_start=False, timezone_fallback=False)

    assert selected[0].is_tie_or_broad_window is True
    assert selected[0].confidence in {"medium", "low"}
    assert len(selected) >= 2  # the user is offered the choice


def test_decide_windows_refuses_a_claim_when_the_interval_touches_zero():
    config = TimeLiftConfig(min_meaningful_lift=0.0)
    windows = [_window(6, 0.30, -0.02), _window(7, 0.10, 0.01)]

    selected = decide_windows(7.0, windows, config, cold_start=False, timezone_fallback=False)

    assert selected[0].is_tie_or_broad_window is True
    assert selected[0].confidence == CONFIDENCE_LOW


def test_decide_windows_degrades_for_cold_start_and_utc_fallback():
    config = TimeLiftConfig(min_meaningful_lift=0.05)
    windows = [_window(6, 0.40, 0.10), _window(7, 0.10, -0.05)]

    cold = decide_windows(7.0, windows, config, cold_start=True, timezone_fallback=False)
    fallback = decide_windows(7.0, windows, config, cold_start=False, timezone_fallback=True)

    for selected in (cold, fallback):
        assert selected[0].confidence == CONFIDENCE_LOW
        assert selected[0].is_tie_or_broad_window is True


def test_decide_windows_without_support_never_claims():
    config = TimeLiftConfig(min_meaningful_lift=0.0)
    windows = [_window(6, 0.40, 0.10, eligible=False), _window(7, 0.10, 0.05, eligible=False)]

    selected = decide_windows(7.0, windows, config, cold_start=False, timezone_fallback=False)

    assert selected[0].confidence == CONFIDENCE_LOW
    assert selected[0].is_tie_or_broad_window is True


@pytest.fixture(scope="module")
def lift_table(tmp_path_factory):
    config = TimeLiftConfig(shrinkage_k=20.0, min_support_posts=5, min_support_users=3, bootstrap_samples=40)
    rows = []
    for weekday in range(7):
        for bucket in range(8):
            for index in range(12):
                rows.append((0, weekday, bucket, f"u{weekday}-{index}", 0.2 + 0.01 * bucket))
    return TimeLiftTable.fit(_residual_frame(rows), config)


def test_recommend_windows_returns_local_windows_with_evidence(lift_table, tmp_path):
    """The response must carry local times, support and the evidence level."""
    service = RecommendationService(
        model_path=tmp_path / "missing-model.txt",
        time_lift_path=tmp_path / "lift.json",
        metrics_path=tmp_path / "metrics.json",
    )
    service.time_lift = lift_table
    service.default_popularity = 6.0

    result = service.recommend_windows(
        user_prior_mean=6.5,
        user_post_count=20,
        title="Yapay zeka ve yazılım",
        tags=["#python"],
        timezone_name="Europe/Istanbul",
        days_ahead=7,
        max_windows=2,
    )

    assert result.timezone_basis == "user_timezone"
    assert result.timezone_fallback is False
    assert len(result.windows) == 2
    for window in result.windows:
        assert isinstance(window, RecommendedWindow)
        # Local times are in the user's zone, and the UTC twin matches the instant.
        assert window.window_start_local.utcoffset() == timedelta(hours=3)
        assert window.window_end_local - window.window_start_local == timedelta(hours=3)
        assert window.window_start_utc == window.window_start_local.astimezone(timezone.utc)
        assert window.window_start_local.hour % 3 == 0
        assert window.time_range_local.endswith("00")
        assert window.evidence_level in {
            "category_weekday_bucket", "category_bucket", "global_weekday_bucket",
            "global_bucket", "neutral",
        }
        assert window.support_post_count >= 0
        assert window.confidence in {"high", "medium", "low"}


def test_recommend_windows_marks_utc_fallback_and_lowers_confidence(lift_table, tmp_path):
    service = RecommendationService(
        model_path=tmp_path / "missing-model.txt",
        time_lift_path=tmp_path / "lift.json",
        metrics_path=tmp_path / "metrics.json",
    )
    service.time_lift = lift_table
    service.default_popularity = 6.0

    result = service.recommend_windows(
        user_prior_mean=6.5, user_post_count=20, title="Yazılım", days_ahead=3, max_windows=2
    )

    assert result.timezone_basis == "utc_fallback"
    assert result.timezone_fallback is True
    assert result.confidence == CONFIDENCE_LOW
    assert all(window.timezone_basis == "utc_fallback" for window in result.windows)
    assert all(window.is_tie_or_broad_window for window in result.windows)


def test_cold_start_response_is_low_confidence(lift_table, tmp_path):
    service = RecommendationService(
        model_path=tmp_path / "missing-model.txt",
        time_lift_path=tmp_path / "lift.json",
        metrics_path=tmp_path / "metrics.json",
    )
    service.time_lift = lift_table
    service.default_popularity = 6.0

    result = service.recommend_windows(
        user_prior_mean=6.0,
        user_post_count=0,
        title="Yeni bir içerik fikri",
        timezone_name="Europe/Istanbul",
        days_ahead=3,
    )

    assert result.history_depth == 0
    assert result.confidence == CONFIDENCE_LOW
    assert result.confidence_label == "Düşük"
    assert all(window.is_tie_or_broad_window for window in result.windows)


def test_missing_lift_table_degrades_to_neutral_instead_of_guessing(tmp_path):
    service = RecommendationService(
        model_path=tmp_path / "missing-model.txt",
        time_lift_path=tmp_path / "missing-lift.json",
        metrics_path=tmp_path / "metrics.json",
    )
    assert service.time_lift is None

    result = service.recommend_windows(
        user_prior_mean=6.0, user_post_count=10, title="Test", timezone_name="Europe/Istanbul", days_ahead=2
    )

    assert all(window.observational_time_lift == 0.0 for window in result.windows)
    assert all(window.evidence_level == LEVEL_NEUTRAL for window in result.windows)
    assert result.confidence == CONFIDENCE_LOW

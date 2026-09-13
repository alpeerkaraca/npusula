"""Tests for the two-layer recommendation service, device reporting, and the advisor engine."""
from datetime import datetime, timedelta, timezone

import pytest

from backend.schemas.post import MediaTypeEnum
from backend.schemas.recommendation import (
    AdvisorRequest,
    RecommendedWindow,
    SimilarPost,
    WindowRecommendation,
)
from backend.services.device import device_manager
from backend.services.gemma_advisor import GemmaAdvisorEngine, format_window_turkish
from backend.services.recommendation import RecommendationService


def test_device_manager_reports_hardware_without_claiming_a_model():
    """The device manager describes hardware; it no longer implies a GPU model exists."""
    info = device_manager.get_info()
    assert "device_type" in info
    assert "device_name" in info
    assert "gpu_available" in info


def _window(
    weekday: int,
    bucket: int,
    label: str,
    lift: float,
    confidence: str = "high",
    tie: bool = False,
    support: int = 1240,
) -> RecommendedWindow:
    base = datetime(2026, 9, 15, bucket * 3, 0, tzinfo=timezone.utc)
    return RecommendedWindow(
        window_start_local=base,
        window_end_local=base + timedelta(hours=3),
        window_start_utc=base,
        window_end_utc=base + timedelta(hours=3),
        weekday=label,
        weekday_index=weekday,
        bucket=bucket,
        time_range_local=f"{bucket * 3:02d}.00–{bucket * 3 + 3:02d}.00",
        base_potential=7.1,
        observational_time_lift=lift,
        confidence=confidence,
        confidence_label={"high": "Yüksek", "medium": "Orta", "low": "Düşük"}[confidence],
        support_post_count=support,
        support_user_count=210,
        evidence_level="category_weekday_bucket",
        is_tie_or_broad_window=tie,
        timezone_basis="user_timezone",
    )


def _recommendation(windows: list[RecommendedWindow], tie: bool = False, fallback: bool = False) -> WindowRecommendation:
    return WindowRecommendation(
        base_potential=7.1,
        primary_category_code=0,
        confidence=windows[0].confidence,
        confidence_label=windows[0].confidence_label,
        is_tie_or_broad_window=tie,
        timezone_basis="utc_fallback" if fallback else "user_timezone",
        timezone_label="UTC" if fallback else "Europe/Istanbul",
        timezone_fallback=fallback,
        history_depth=3,
        windows=windows,
    )


def test_recommendation_service_has_no_gpu_model():
    service = RecommendationService()
    assert not hasattr(service, "gpu_model")


def test_recommendation_service_window_contract():
    service = RecommendationService()
    result = service.recommend_windows(
        user_prior_mean=6.5,
        user_post_count=15,
        title="Yapay zeka ile kod üretimi",
        tags=["#yapayzeka"],
        media_type=MediaTypeEnum.PHOTO,
        topic="Yapay Zeka",
        max_windows=3,
        timezone_name="Europe/Istanbul",
    )

    assert len(result.windows) == 3
    for window in result.windows:
        assert 0 <= window.weekday_index <= 6
        assert 0 <= window.bucket <= 7
        assert window.window_end_local - window.window_start_local == timedelta(hours=3)
        assert window.confidence in {"high", "medium", "low"}
        assert window.evidence_level in {
            "category_weekday_bucket", "category_bucket", "global_weekday_bucket",
            "global_bucket", "neutral",
        }
        # No window may present itself as a strict winner without evidence.
        if window.confidence == "high":
            assert window.is_tie_or_broad_window is False
            assert window.support_post_count > 0


def test_format_window_turkish():
    window = _window(1, 6, "Salı", 0.12)
    assert format_window_turkish(window) == "Salı 18.00–21.00"


def test_gemma_advisor_prompt_building():
    engine = GemmaAdvisorEngine()
    recommendation = _recommendation([
        _window(1, 6, "Salı", 0.22),
        _window(3, 6, "Perşembe", 0.11),
        _window(6, 4, "Pazar", 0.02),
    ])
    posts = [
        SimilarPost(
            post_id="p1",
            title="Derin Öğrenme Mimarileri",
            weekday=1,
            hour=21,
            popularity_score=15.0,
            similarity=0.92,
            tags=["#yapayzeka", "#derinogrenme"],
        )
    ]

    prompt = engine.build_prompt(
        idea="Yapay zeka ile kod üretimi",
        topic="Yapay Zeka",
        media_type=MediaTypeEnum.PHOTO,
        window_recommendation=recommendation,
        suggested_tags=["#yapayzeka", "#kodlama"],
        similar_posts=posts,
    )

    assert "<start_of_turn>user" in prompt
    assert "<end_of_turn>" in prompt
    assert "<start_of_turn>model" in prompt
    assert "Yapay zeka ile kod üretimi" in prompt
    assert "Salı 18.00–21.00" in prompt
    # Mandatory wording rules
    assert "Kesin nedensel iddia kurma" in prompt
    assert "Geçmiş gözlemlerde desteklenen pencere" in prompt
    assert "doğrulanmış etiketlerden üret" in prompt


def test_gemma_advisor_prompt_discloses_utc_fallback():
    engine = GemmaAdvisorEngine()
    recommendation = _recommendation([_window(1, 6, "Salı", 0.05)], tie=True, fallback=True)

    prompt = engine.build_prompt(
        idea="Kahve",
        topic="Yaşam",
        media_type=MediaTypeEnum.PHOTO,
        window_recommendation=recommendation,
        suggested_tags=[],
        similar_posts=[],
    )

    assert "saat dilimi bilinmiyor" in prompt.lower()
    assert "Doğrulanmış etiket yok" in prompt


def test_gemma_advisor_explanation_fallback_uses_window_language():
    recommendation = _recommendation([
        _window(0, 6, "Pazartesi", 0.18),
        _window(2, 7, "Çarşamba", 0.04),
    ])
    offline = GemmaAdvisorEngine(api_url="http://127.0.0.1:9", timeout_seconds=0.3)

    explanation = offline.generate_explanation(
        idea="Yeni nesil oyun motorları ve performans",
        topic="Oyun",
        media_type=MediaTypeEnum.VIDEO,
        window_recommendation=recommendation,
        suggested_tags=["#oyun", "#teknoloji"],
        similar_posts=[],
    )

    assert "Pazartesi 18.00–21.00" in explanation
    assert "gözlemsel" in explanation.lower()
    assert "nedensellik iddiası değil" in explanation
    assert "#oyun" in explanation
    assert "Strateji Önerisi" in explanation


def test_gemma_advisor_fallback_offers_a_choice_for_broad_windows():
    recommendation = _recommendation([
        _window(0, 6, "Pazartesi", 0.02, confidence="low", tie=True),
        _window(2, 7, "Çarşamba", 0.01, confidence="low", tie=True),
    ], tie=True)
    offline = GemmaAdvisorEngine(api_url="http://127.0.0.1:9", timeout_seconds=0.3)

    explanation = offline.generate_explanation(
        idea="Aile yürüyüşü",
        topic="Yaşam",
        media_type=MediaTypeEnum.PHOTO,
        window_recommendation=recommendation,
        suggested_tags=[],
        similar_posts=[],
    )

    assert "belirgin değil" in explanation
    assert "veya" in explanation
    assert "Düşük" in explanation


def test_gemma_advisor_live_explanation_is_substantive():
    """Live LLM answer must be substantive; skipped when Ollama is not running."""
    try:
        import httpx

        with httpx.Client(timeout=1.0) as client:
            if client.get("http://127.0.0.1:11434/api/tags").status_code != 200:
                pytest.skip("Ollama is not running")
    except Exception:
        pytest.skip("Ollama is not running")

    recommendation = _recommendation([_window(0, 6, "Pazartesi", 0.18)])
    live = GemmaAdvisorEngine().generate_explanation(
        idea="Yeni nesil oyun motorları ve performans",
        topic="Oyun",
        media_type=MediaTypeEnum.VIDEO,
        window_recommendation=recommendation,
        suggested_tags=["#oyun"],
        similar_posts=[],
    )
    assert len(live) >= 50


def test_advisor_request_rejects_out_of_range_offset():
    with pytest.raises(Exception):
        AdvisorRequest(user_id="u", idea="fikir", utc_offset_minutes=9999)

"""Tests for residual recommendations, device reporting, and the advisor engine."""
from datetime import datetime, timezone
import pytest
import torch

from backend.config import settings
from backend.models.tabular_nn import PopularityTabularNN
from backend.schemas.post import MediaTypeEnum
from backend.schemas.recommendation import AdvisorRequest, CandidateSlot, SimilarPost
from backend.services.device import device_manager
from backend.services.gemma_advisor import GemmaAdvisorEngine, format_slot_turkish
from backend.services.recommendation import RecommendationService


def test_device_manager_gpu_detection():
    info = device_manager.get_info()
    assert "device_type" in info
    assert "device_name" in info
    # On this machine, DirectML with AMD Radeon RX 9070 XT should be active
    assert info["gpu_available"] is True
    assert "AMD Radeon RX 9070 XT" in info["device_name"]


def test_gpu_tabular_nn_forward():
    device = device_manager.get_device()
    model = PopularityTabularNN(num_categories=14, num_continuous=31).to(device)
    model.eval()

    batch_size = 4
    cat_ids = torch.zeros(batch_size, dtype=torch.long, device=device)
    media_ids = torch.zeros(batch_size, dtype=torch.long, device=device)
    weekend_ids = torch.zeros(batch_size, dtype=torch.long, device=device)
    continuous = torch.ones((batch_size, 31), dtype=torch.float32, device=device)

    with torch.no_grad():
        preds = model(cat_ids, media_ids, weekend_ids, continuous)

    assert preds.shape == (batch_size,)
    assert not torch.isnan(preds).any()


def test_recommendation_service_residual_contract():
    service = RecommendationService()
    assert not hasattr(service, "gpu_model")

    slots = service.recommend_slots(
        user_prior_mean=6.5,
        user_post_count=15,
        title="PyTorch GPU Test",
        tags=["#yapayzeka"],
        media_type=MediaTypeEnum.PHOTO,
        topic="Yapay Zeka",
        top_k=3,
    )
    assert len(slots) == 3
    for s in slots:
        assert 0 <= s.weekday <= 6
        assert 0 <= s.hour <= 23
        assert 0.0 <= s.predicted_popularity <= 20.0


def test_gemma_advisor_prompt_building():
    engine = GemmaAdvisorEngine()
    now = datetime(2026, 9, 15, 21, 0, tzinfo=timezone.utc)
    slots = [
        CandidateSlot(datetime_utc=now, weekday=1, hour=21, predicted_popularity=14.2, label="Çok güçlü"),
        CandidateSlot(datetime_utc=now, weekday=3, hour=18, predicted_popularity=13.8, label="Güçlü"),
        CandidateSlot(datetime_utc=now, weekday=6, hour=12, predicted_popularity=13.1, label="Orta"),
    ]
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
        slots=slots,
        suggested_tags=["#yapayzeka", "#kodlama"],
        similar_posts=posts,
    )
    assert "<start_of_turn>user" in prompt
    assert "<end_of_turn>" in prompt
    assert "<start_of_turn>model" in prompt
    assert "Yapay zeka ile kod üretimi" in prompt
    assert "Salı 21:00" in prompt
    assert "en güçlü aday" in prompt


def test_gemma_advisor_explanation_generation():
    now = datetime(2026, 9, 14, 18, 0, tzinfo=timezone.utc)
    slots = [
        CandidateSlot(datetime_utc=now, weekday=0, hour=18, predicted_popularity=12.5, label="Çok güçlü"),
        CandidateSlot(datetime_utc=now, weekday=2, hour=21, predicted_popularity=11.8, label="Güçlü"),
    ]
    kwargs = dict(
        idea="Yeni nesil oyun motorları ve performans",
        topic="Oyun",
        media_type=MediaTypeEnum.VIDEO,
        slots=slots,
        suggested_tags=["#oyun", "#teknoloji"],
        similar_posts=[],
    )

    # Deterministic fallback when the LLM is unreachable
    offline = GemmaAdvisorEngine(api_url="http://127.0.0.1:9", timeout_seconds=0.3)
    fallback = offline.generate_explanation(**kwargs)
    assert "en güçlü aday" in fallback
    assert "Pazartesi 18:00" in fallback
    assert "#oyun" in fallback
    assert "Strateji Önerisi" in fallback

    # Live LLM response must be a substantive, varied answer (skip when
    # Ollama is not running in this environment)
    try:
        import httpx
        with httpx.Client(timeout=1.0) as client:
            if client.get("http://127.0.0.1:11434/api/tags").status_code != 200:
                pytest.skip("Ollama is not running")
    except Exception:
        pytest.skip("Ollama is not running")

    live = GemmaAdvisorEngine().generate_explanation(**kwargs)
    assert len(live) >= 50
    assert "en güçlü aday" in live.lower()

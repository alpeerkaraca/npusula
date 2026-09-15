"""Regression tests for advisor pipeline quality (topic, category, retrieval)."""
import pytest
from fastapi.testclient import TestClient

from backend.app import app
from backend.services.canonical_taxonomy import classify_post_category
from backend.services.profile import ProfileService


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


def test_family_idea_classifies_to_yasam():
    """Everyday family content must map to Yaşam, not fall back to a tech topic."""
    ps = ProfileService()
    cases = [
        "Ailemle geçirdiğim mutlu bir haftasonu",
        "Hafta sonu kahvaltı ve aile yürüyüşü",
        "Evlilik yıldönümü kutlaması",
    ]
    for text in cases:
        topic = ps.classify_text_topic(text, fallback_topic="Yazılım")
        assert topic == "Yaşam", f"{text!r} -> {topic!r}"


def test_family_idea_maps_to_social_lifestyle():
    """Category matching must be word-boundary aware and lifestyle aware."""
    assert classify_post_category("Ailemle geçirdiğim mutlu bir haftasonu", None, None, None)["primary_category"] == "social_lifestyle"
    assert classify_post_category("Ev dekorasyonu ve mobilya seçimi", None, None, None)["primary_category"] == "social_lifestyle"


def test_category_matching_is_word_boundary_aware():
    """Substring hazards: 'ai' inside 'ailemle', 'ev' inside 'evlilik'."""
    # "ai" is a substring of "ailemle" and must not map it to technology
    assert classify_post_category("ailemle piknik planı", None, None, None)["primary_category"] == "social_lifestyle"
    # "ev" inside "evlilik" must not map to automotive/electric_vehicles
    assert classify_post_category("evlilik yıldönümü", None, None, None)["primary_category"] == "social_lifestyle"
    # real technology keywords still match
    assert classify_post_category("Python ile yapay zeka modelleri", None, None, None)["primary_category"] == "technology"
    assert classify_post_category("Derin öğrenme ve transformer mimarileri", None, None, None)["primary_category"] == "technology"
    assert classify_post_category("Elektrikli araç batarya ömrü", None, None, None)["primary_category"] == "automotive"


def test_sports_ideas_classify_to_spor():
    """Sports vocabulary (including inflected forms) must map to Spor."""
    ps = ProfileService()
    for text in ["güreş maçı heyecanı", "boks antrenmanı", "voleybol turnuvası"]:
        topic = ps.classify_text_topic(text, fallback_topic="Yazılım")
        assert topic == "Spor", f"{text!r} -> {topic!r}"


def test_sports_category_mapping():
    """Sports ideas must map to sports_fitness in the canonical taxonomy."""
    assert classify_post_category("amerikan güreşi izledik", None, None, None)["primary_category"] == "sports_fitness"
    assert classify_post_category("voleybol turnuvası", None, None, None)["primary_category"] == "sports_fitness"


def test_llm_topic_classifier_fails_open():
    """Unreachable LLM must return None so callers keep their fallback."""
    from backend.services.gemma_advisor import GemmaAdvisorEngine

    engine = GemmaAdvisorEngine(api_url="http://127.0.0.1:9", timeout_seconds=0.3)
    assert engine.classify_topic("herhangi bir fikir", ProfileService().topic_names) is None


def test_advisor_api_wrestling_idea_quality(client):
    """API response for a wrestling idea must be sports, not the user's tech profile."""
    try:
        import httpx
        with httpx.Client(timeout=1.0) as check:
            if check.get("http://127.0.0.1:11434/api/tags").status_code != 200:
                pytest.skip("Ollama is not running")
    except Exception:
        pytest.skip("Ollama is not running")

    response = client.post("/api/recommend/advisor", json={
        "user_id": "31253@N15",
        "idea": "amerikan güreşi izledik",
        "media_type": "video",
        "horizon": "next_7_days",
    })
    assert response.status_code == 200
    data = response.json()
    assert data["topic"] == "Spor"
    assert data["primary_category"] == "sports_fitness"


def test_advisor_api_family_idea_quality(client):
    """API response for a family weekend idea must be lifestyle, not tech."""
    response = client.post("/api/recommend/advisor", json={
        "user_id": "31253@N15",
        "idea": "Ailemle geçirdiğim mutlu bir haftasonu",
        "media_type": "video",
        "horizon": "next_7_days",
    })
    assert response.status_code == 200
    data = response.json()
    assert data["topic"] == "Yaşam"
    assert data["primary_category"] == "social_lifestyle"
    # The corpus is English-only; Turkish ideas legitimately retrieve none.
    assert len(data["similar_posts"]) <= 5
    # Tags must reflect the lifestyle topic, not random English photo tags.
    assert "#model" not in data["accepted_tags"]
    assert "#dress" not in data["accepted_tags"]
    assert any(tag in {"#yaşam", "#lifestyle", "#günlükyaşam"} for tag in data["accepted_tags"])


def test_category_is_reported_as_a_fallback_when_nothing_asserts_it(client):
    """Neither the idea text nor the topic matched, so the category is a guess.

    "Eğitim" is in the topic vocabulary but has no canonical category, which
    makes it the one case where the ladder bottoms out. The response must say
    so rather than presenting the label as knowledge.
    """
    response = client.post("/api/recommend/advisor", json={
        "user_id": "31253@N15",
        "idea": "üniversite sınavına hazırlık ve ders çalışma yöntemleri",
        "media_type": "photo",
        "horizon": "next_7_days",
        "timezone": "Europe/Istanbul",
    })
    assert response.status_code == 200
    data = response.json()

    assert data["text_category"]
    assert data["category_source"] == "text"
    assert data["primary_category_is_fallback"] is True
    assert data["primary_category_confidence"] <= 0.30


def test_suggested_tags_are_aligned_semantics_only_and_deduplicated(client):
    """Only verified tags may be suggested, and never twice (plan §6.2)."""
    response = client.post("/api/recommend/advisor", json={
        "user_id": "31253@N15",
        "idea": "Büyük dil modellerinde prompt mühendisliği ve dikkat mekanizmaları",
        "media_type": "photo",
        "horizon": "next_7_days",
        "timezone": "Europe/Istanbul",
    })
    assert response.status_code == 200
    data = response.json()

    # The idea text matches no keyword, so the declared topic supplies the
    # category. That is asserted evidence with a named source, not an
    # unasserted fallback.
    assert data["category_source"] == "topic"
    assert data["primary_category_is_fallback"] is False
    assert data["primary_category_confidence"] > 0.30

    assert data["suggested_tags"], "a technology idea must still get verified tags"
    assert len(data["suggested_tags"]) <= 3
    assert set(data["suggested_tags"]) <= set(data["accepted_tags"])
    assert all(tag.startswith("#") for tag in data["suggested_tags"])

    lowered = [tag.lower() for tag in data["accepted_tags"]]
    assert len(lowered) == len(set(lowered)), f"duplicate tags reported: {data['accepted_tags']}"


def test_turkish_tags_are_recognized_by_taxonomy():
    """Turkish hashtags must align to the semantic taxonomy of their own category."""
    from backend.services.tag_taxonomy import align_tags

    cases = [
        (["#yaşam", "#lifestyle"], "social_lifestyle"),
        (["#spor", "#antrenman"], "sports_fitness"),
        (["#aile", "#mutluluk"], "social_lifestyle"),
        (["#yapayzeka", "#kodlama"], "technology"),
        (["#kahve", "#yemek"], "food_dining"),
    ]
    for tags, canonical_category in cases:
        result = align_tags(tags, context_category=canonical_category)
        assert result["aligned_semantic"], f"Turkish tags not aligned for {canonical_category}: {tags}"
        assert not result["nsfw_filtered"]
        assert not result["mismatched_semantic"]

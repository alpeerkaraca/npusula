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
    assert classify_post_category("Elektrikli araç batarya teknolojisi", None, None, None)["primary_category"] == "automotive"


def test_advisor_api_family_idea_quality(client):
    """API response for a family weekend idea must be lifestyle, not tech."""
    response = client.post("/api/recommend/advisor", json={
        "user_id": "demo_user_01",
        "idea": "Ailemle geçirdiğim mutlu bir haftasonu",
        "media_type": "video",
        "horizon": "next_7_days",
    })
    assert response.status_code == 200
    data = response.json()
    assert data["topic"] == "Yaşam"
    assert data["primary_category"] == "social_lifestyle"
    assert data["similar_posts"], "similar posts must not be empty"

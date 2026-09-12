"""End-to-end integration tests for all 7 FastAPI endpoints."""
from fastapi.testclient import TestClient
import pytest

from backend.app import app


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as test_client:
        yield test_client


def test_health_endpoint(client):
    response = client.get("/api/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert "version" in data
    assert "qdrant_connected" in data
    assert "gpu" in data
    assert "advisor_model" in data
    assert data["advisor_model"] == "google/gemma-4-E4B-it"


def test_demo_users_endpoint(client):
    response = client.get("/api/demo-users")
    assert response.status_code == 200
    users = response.json()
    assert len(users) == 3
    user_ids = [u["user_id"] for u in users]
    assert "demo_user_01" in user_ids
    assert "demo_user_02" in user_ids
    assert "demo_user_03" in user_ids


def test_profile_aligned_user(client):
    response = client.get("/api/profile/demo_user_01")
    assert response.status_code == 200
    data = response.json()
    assert data["user_id"] == "demo_user_01"
    assert data["drift_detected"] is False
    assert data["question"] is None
    assert len(data["active_recommendation_topics"]) > 0


def test_profile_drifted_user(client):
    response = client.get("/api/profile/demo_user_02")
    assert response.status_code == 200
    data = response.json()
    assert data["user_id"] == "demo_user_02"
    assert data["drift_detected"] is True
    assert data["question"] is not None


def test_profile_decision_accept(client):
    response = client.post("/api/profile/demo_user_02/decision", json={"accept": True})
    assert response.status_code == 200
    data = response.json()
    # Recommendation should shift to behavioral top topic
    assert data["active_recommendation_topics"][0]["topic"] == data["behavioral_topics"][0]["topic"]


def test_quick_recommendation_aligned_user(client):
    response = client.get("/api/recommend/quick/demo_user_01")
    assert response.status_code == 200
    data = response.json()
    assert data["user_id"] == "demo_user_01"
    assert len(data["slots"]) == 3
    assert data["cold_start"] is False
    assert "Pazartesi" in data["explanation"] or "Salı" in data["explanation"] or "Çarşamba" in data["explanation"] or "Perşembe" in data["explanation"] or "Cuma" in data["explanation"] or "Cumartesi" in data["explanation"] or "Pazar" in data["explanation"]


def test_quick_recommendation_cold_start(client):
    response = client.get("/api/recommend/quick/demo_user_03")
    assert response.status_code == 200
    data = response.json()
    assert data["user_id"] == "demo_user_03"
    assert data["cold_start"] is True
    assert len(data["slots"]) == 3


def test_advisor_endpoint_success(client):
    payload = {
        "user_id": "demo_user_01",
        "idea": "Yeni nesil üretken yapay zeka modelleri ve kullanım alanları",
        "media_type": "photo",
        "horizon": "next_7_days",
    }
    response = client.post("/api/recommend/advisor", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["topic"] == "Yapay Zeka"
    assert data["primary_category"] == "technology"
    assert len(data["recommendations"]) == 3
    assert isinstance(data["accepted_tags"], list)
    assert isinstance(data["rejected_tags"], list)
    assert data["history_depth"] in {
        "cold_start", "very_low_history", "low_history", "medium_history", "high_history"
    }
    assert data["confidence_level"] in {"Düşük", "Orta", "Yüksek"}
    assert data["service_mode"] == "deep_advisor"
    assert all("relative_potential" in slot and "confidence_level" in slot for slot in data["recommendations"])
    assert len(data["suggested_tags"]) <= 3
    assert len(data["similar_posts"]) > 0
    assert "en güçlü aday" in data["explanation"].lower()


def test_advisor_strict_pydantic_rejection(client):
    """Strict Pydantic should reject extra keys or invalid empty idea string."""
    # Test 1: Empty idea string violates min_length=1
    response = client.post("/api/recommend/advisor", json={
        "user_id": "demo_user_01",
        "idea": "",
        "media_type": "photo",
    })
    assert response.status_code == 422

    # Test 2: Extra forbidden field
    response = client.post("/api/recommend/advisor", json={
        "user_id": "demo_user_01",
        "idea": "Valid idea",
        "media_type": "photo",
        "forbidden_extra_field": 123,
    })
    assert response.status_code == 422


def test_model_metrics_endpoint(client):
    response = client.get("/api/model/metrics")
    assert response.status_code == 200
    data = response.json()
    assert "baseline_mae" in data
    assert "model_mae" in data
    assert "baseline_spearman" in data
    assert "model_spearman" in data
    assert len(data["feature_importance"]) > 0

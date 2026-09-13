"""End-to-end integration tests for all FastAPI endpoints.

The product contract these assert is the *window* contract: local start/end
times, evidence level and confidence — never a single "best hour".
"""
from datetime import datetime, timedelta
from fastapi.testclient import TestClient
import pytest

from backend.app import app

TR_WEEKDAYS = ["Pazartesi", "Salı", "Çarşamba", "Perşembe", "Cuma", "Cumartesi", "Pazar"]

WINDOW_KEYS = {
    "window_start_local", "window_end_local", "window_start_utc", "window_end_utc",
    "weekday", "weekday_index", "bucket", "time_range_local", "base_potential",
    "observational_time_lift", "relative_potential", "confidence", "confidence_label",
    "support_post_count", "support_user_count", "evidence_level", "lift_ci_low",
    "lift_ci_high", "is_tie_or_broad_window", "timezone_basis",
}


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
    """Synthetic demo accounts were removed; the endpoint stays for clients."""
    response = client.get("/api/demo-users")
    assert response.status_code == 200
    assert response.json() == []


def test_profile_diffuse_user_no_drift(client):
    """A real SMPD user with diffuse topics must not trigger drift."""
    response = client.get("/api/profile/60519@N0")
    assert response.status_code == 200
    data = response.json()
    assert data["user_id"] == "60519@N0"
    assert data["drift_detected"] is False
    assert data["question"] is None
    assert len(data["active_recommendation_topics"]) > 0


def test_profile_drifted_user(client):
    """A real SMPD user concentrated in an undeclared topic drifts."""
    response = client.get("/api/profile/36743@N91")
    assert response.status_code == 200
    data = response.json()
    assert data["user_id"] == "36743@N91"
    assert data["drift_detected"] is True
    assert data["question"] is not None


def test_profile_decision_accept(client):
    response = client.post("/api/profile/36743@N91/decision", json={"accept": True})
    assert response.status_code == 200
    data = response.json()
    # Recommendation should shift to behavioral top topic
    assert data["active_recommendation_topics"][0]["topic"] == data["behavioral_topics"][0]["topic"]


def test_quick_recommendation_with_history(client):
    """A real SMPD user with rich posting history gets warm-start windows."""
    response = client.get("/api/recommend/quick/31253@N15", params={"timezone": "Europe/Istanbul"})
    assert response.status_code == 200
    data = response.json()
    assert data["user_id"] == "31253@N15"
    assert data["cold_start"] is False
    assert len(data["windows"]) == 3
    assert data["timezone_basis"] == "user_timezone"
    assert data["confidence"] in {"high", "medium", "low"}

    for window in data["windows"]:
        assert WINDOW_KEYS <= set(window)
        assert window["confidence"] in {"high", "medium", "low"}
        assert window["confidence_label"] in {"Yüksek", "Orta", "Düşük"}
        assert window["weekday"] in TR_WEEKDAYS
        assert window["time_range_local"].count("–") == 1
        assert 0 <= window["weekday_index"] <= 6
        assert 0 <= window["bucket"] <= 7
        # Start/end are exactly three local hours apart and in the user's zone.
        start = datetime.fromisoformat(window["window_start_local"])
        end = datetime.fromisoformat(window["window_end_local"])
        assert end - start == timedelta(hours=3)
        assert start.utcoffset() == timedelta(hours=3)
        assert start.hour % 3 == 0
        assert datetime.fromisoformat(window["window_start_utc"]) == start


def test_quick_recommendation_defaults_to_utc_and_says_so(client):
    response = client.get("/api/recommend/quick/31253@N15")
    assert response.status_code == 200
    data = response.json()
    assert data["timezone_basis"] == "utc_fallback"
    for window in data["windows"]:
        assert window["timezone_basis"] == "utc_fallback"
        assert datetime.fromisoformat(window["window_start_local"]).utcoffset() == timedelta(0)


def test_quick_recommendation_accepts_a_fixed_offset(client):
    response = client.get("/api/recommend/quick/31253@N15", params={"utc_offset_minutes": 180})
    assert response.status_code == 200
    window = response.json()["windows"][0]
    assert datetime.fromisoformat(window["window_start_local"]).utcoffset() == timedelta(hours=3)


def test_quick_recommendation_cold_start(client):
    """An unknown user id (no posts) exercises the cold-start path: low confidence."""
    response = client.get("/api/recommend/quick/cold_start_user", params={"timezone": "Europe/Istanbul"})
    assert response.status_code == 200
    data = response.json()
    assert data["user_id"] == "cold_start_user"
    assert data["cold_start"] is True
    assert len(data["windows"]) == 3
    assert data["confidence"] == "low"
    assert data["confidence_label"] == "Düşük"
    assert all(window["is_tie_or_broad_window"] for window in data["windows"])
    assert "belirgin değil" in data["explanation"] or "desteklenen pencere" in data["explanation"]


def test_advisor_endpoint_success(client):
    payload = {
        "user_id": "31253@N15",
        "idea": "Yeni nesil üretken yapay zeka modelleri ve kullanım alanları",
        "media_type": "photo",
        "horizon": "next_7_days",
        "timezone": "Europe/Istanbul",
    }
    response = client.post("/api/recommend/advisor", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["topic"] == "Yapay Zeka"
    assert data["primary_category"] == "technology"
    assert len(data["windows"]) == 3
    assert isinstance(data["accepted_tags"], list)
    assert isinstance(data["rejected_tags"], list)
    assert isinstance(data["unknown_tags"], list)
    assert data["history_depth"] in {
        "cold_start", "very_low_history", "low_history", "medium_history", "high_history"
    }
    assert data["confidence"] in {"high", "medium", "low"}
    assert data["confidence_level"] in {"Düşük", "Orta", "Yüksek"}
    assert data["timezone_basis"] == "user_timezone"
    assert data["timezone_fallback"] is False
    assert data["service_mode"] == "deep_advisor"
    assert data["model_version"].startswith("base-potential-lgbm")
    assert len(data["suggested_tags"]) <= 3
    # The corpus is English-only; Turkish ideas may legitimately retrieve none
    assert len(data["similar_posts"]) <= 5


def test_advisor_explanation_never_claims_causality(client):
    """Mandatory wording rules (plan §6.2) must hold in the deterministic fallback."""
    payload = {
        "user_id": "31253@N15",
        "idea": "Ailemle geçirdiğim mutlu bir haftasonu",
        "media_type": "video",
        "horizon": "next_7_days",
        "timezone": "Europe/Istanbul",
    }
    data = client.post("/api/recommend/advisor", json=payload).json()
    explanation = data["explanation"].lower()

    assert explanation
    for forbidden in ("kesinlikle en iyi", "mutlaka daha fazla etkileşim", "nedensel olarak en iyi"):
        assert forbidden not in explanation


def test_advisor_timezone_fallback_is_disclosed(client):
    payload = {
        "user_id": "31253@N15",
        "idea": "Kahve demleme teknikleri",
        "media_type": "photo",
        "horizon": "next_7_days",
    }
    data = client.post("/api/recommend/advisor", json=payload).json()

    assert data["timezone_fallback"] is True
    assert data["timezone_basis"] == "utc_fallback"
    assert "UTC" in data["explanation"]


def test_advisor_strict_pydantic_rejection(client):
    """Strict Pydantic should reject extra keys or invalid empty idea string."""
    response = client.post("/api/recommend/advisor", json={
        "user_id": "test_user",
        "idea": "",
        "media_type": "photo",
    })
    assert response.status_code == 422

    response = client.post("/api/recommend/advisor", json={
        "user_id": "test_user",
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

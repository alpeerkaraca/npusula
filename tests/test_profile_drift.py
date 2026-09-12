"""Tests for behavioral topic extraction, drift detection, and decision updates."""
import pytest
from backend.adapters.repository import PostRepository, UserRepository
from backend.services.profile import ProfileService


@pytest.fixture
def repos():
    return PostRepository(), UserRepository(), ProfileService()


def test_aligned_user_no_drift(repos):
    post_repo, user_repo, prof_service = repos
    user_id = "demo_user_01"

    declared = user_repo.get_declared_profile(user_id)
    posts = post_repo.get_user_history(user_id)
    behavioral = prof_service.compute_behavioral_profile(user_id, posts)
    status = prof_service.get_profile_status(declared, behavioral)

    assert status.user_id == user_id
    assert not status.drift_detected
    assert status.question is None
    assert status.evidence_post_count == 30
    assert status.behavioral_topics[0].topic in ["Yapay Zeka", "Yazılım"]


def test_drifted_user_triggers_drift_and_question(repos):
    post_repo, user_repo, prof_service = repos
    user_id = "demo_user_02"

    declared = user_repo.get_declared_profile(user_id)
    posts = post_repo.get_user_history(user_id)
    behavioral = prof_service.compute_behavioral_profile(user_id, posts)
    status = prof_service.get_profile_status(declared, behavioral)

    assert status.user_id == user_id
    assert status.drift_detected is True
    assert status.question is not None
    assert "Yapay Zeka" in status.question
    assert "Teknoloji Trendleri" in status.question or "Girişimcilik" in status.question
    assert status.evidence_post_count == 25


def test_user_accept_decision_shifts_active_recommendation_topics(repos):
    post_repo, user_repo, prof_service = repos
    user_id = "demo_user_02"

    declared = user_repo.get_declared_profile(user_id)
    posts = post_repo.get_user_history(user_id)
    behavioral = prof_service.compute_behavioral_profile(user_id, posts)

    # Before accept decision
    initial_status = prof_service.get_profile_status(declared, behavioral)
    initial_top_rec = initial_status.active_recommendation_topics[0].topic

    # Record accept decision
    prof_service.record_decision(user_id, accept=True)
    updated_status = prof_service.get_profile_status(declared, behavioral)

    # After accept, top recommendation topic should shift to behavioral top topic
    assert updated_status.active_recommendation_topics[0].topic == behavioral.top_topic

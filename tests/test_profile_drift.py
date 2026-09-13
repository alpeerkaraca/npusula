"""Tests for behavioral topic extraction, drift detection, and decision updates.

Uses real SMPD dataset users (the synthetic demo fixtures were removed).
- DIFFUSE_USER: 30 recent posts with spread-out topics (top weight < 0.40) -> no drift.
- DRIFT_USER: 30 recent posts strongly concentrated in one topic not declared
  by default -> drift question triggered.
"""
import pytest
from backend.adapters.repository import PostRepository, UserRepository
from backend.services.profile import ProfileService

DIFFUSE_USER = "60519@N0"
DRIFT_USER = "36743@N91"


@pytest.fixture
def repos():
    return PostRepository(), UserRepository(), ProfileService()


def test_diffuse_user_no_drift(repos):
    post_repo, user_repo, prof_service = repos

    declared = user_repo.get_declared_profile(DIFFUSE_USER)
    posts = post_repo.get_user_history(DIFFUSE_USER)
    behavioral = prof_service.compute_behavioral_profile(DIFFUSE_USER, posts)
    status = prof_service.get_profile_status(declared, behavioral)

    assert status.user_id == DIFFUSE_USER
    assert not status.drift_detected
    assert status.question is None
    assert status.evidence_post_count == 30
    assert len(status.behavioral_topics) > 0


def test_drifted_user_triggers_drift_and_question(repos):
    post_repo, user_repo, prof_service = repos

    declared = user_repo.get_declared_profile(DRIFT_USER)
    posts = post_repo.get_user_history(DRIFT_USER)
    behavioral = prof_service.compute_behavioral_profile(DRIFT_USER, posts)
    status = prof_service.get_profile_status(declared, behavioral)

    assert status.user_id == DRIFT_USER
    assert status.drift_detected is True
    assert status.question is not None
    assert behavioral.top_topic in status.question
    assert status.evidence_post_count == 30


def test_user_accept_decision_shifts_active_recommendation_topics(repos):
    post_repo, user_repo, prof_service = repos

    declared = user_repo.get_declared_profile(DRIFT_USER)
    posts = post_repo.get_user_history(DRIFT_USER)
    behavioral = prof_service.compute_behavioral_profile(DRIFT_USER, posts)

    prof_service.record_decision(DRIFT_USER, accept=True)
    updated_status = prof_service.get_profile_status(declared, behavioral)

    assert updated_status.active_recommendation_topics[0].topic == behavioral.top_topic

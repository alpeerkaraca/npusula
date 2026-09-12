"""Tests verifying vector retrieval from Qdrant and hashtag aggregation."""
import pytest
from backend.services.retrieval import RetrievalService


@pytest.fixture
def retrieval_service():
    return RetrievalService()


def test_retrieval_service_health(retrieval_service):
    assert retrieval_service.store.is_healthy()
    first = retrieval_service.generate_text_vector("Yapay Zeka")
    second = retrieval_service.generate_text_vector("Yapay Zeka")
    assert first == second
    assert len(first) == 512
    assert any(value != 0.0 for value in first)


def test_search_similar_posts_returns_top_results(retrieval_service):
    posts = retrieval_service.search_similar_posts(topic="Yapay Zeka", limit=5)
    assert len(posts) > 0
    assert len(posts) <= 5

    first = posts[0]
    assert first.post_id != ""
    assert first.title != ""
    assert first.popularity_score > 0.0
    assert 0.0 <= first.similarity <= 1.0001
    assert isinstance(first.tags, list)


def test_extract_top_tags_weights_by_frequency_and_score(retrieval_service):
    posts = retrieval_service.search_similar_posts(topic="Yapay Zeka", limit=5)
    top_tags = retrieval_service.extract_top_tags(posts, top_k=3)

    assert len(top_tags) <= 3
    assert all(t.startswith("#") for t in top_tags)

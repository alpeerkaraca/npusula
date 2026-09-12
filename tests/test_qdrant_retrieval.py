"""Tests verifying vector retrieval from Qdrant and hashtag aggregation."""
import pytest
from backend.schemas.recommendation import SimilarPost
from backend.services.retrieval import RetrievalService


@pytest.fixture
def retrieval_service():
    return RetrievalService()


def _post(similarity: float, tags: list[str], popularity: float = 9.0) -> SimilarPost:
    return SimilarPost(
        post_id="test-1",
        title="test post",
        hour=12,
        weekday=0,
        popularity_score=popularity,
        similarity=similarity,
        tags=tags,
    )


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


def test_search_filters_degenerate_matches(retrieval_service):
    """Zero-overlap queries must return nothing instead of arbitrary posts."""
    assert retrieval_service.search_similar_posts(topic="zzzqqq wwwx", limit=5) == []


def test_extract_top_tags_weights_by_frequency_and_score(retrieval_service):
    posts = retrieval_service.search_similar_posts(topic="Yapay Zeka", limit=5)
    top_tags = retrieval_service.extract_top_tags(posts, top_k=3)

    assert len(top_tags) <= 3
    assert all(t.startswith("#") for t in top_tags)


def test_extract_top_tags_ignores_weak_matches(retrieval_service):
    """Tags from barely-similar posts are noise; topic defaults must be used."""
    weak = [_post(0.05, ["#model", "#dress"]), _post(0.12, ["#architecture"])]
    tags = retrieval_service.extract_top_tags(weak, top_k=3, topic="Yaşam")

    assert "#model" not in tags
    assert "#dress" not in tags
    assert "#architecture" not in tags
    assert tags[0] == "#yaşam"


def test_extract_top_tags_uses_strong_matches(retrieval_service):
    """Genuinely similar posts still drive tag extraction."""
    strong = [_post(0.55, ["#coffee", "#breakfast"])]
    tags = retrieval_service.extract_top_tags(strong, top_k=2, topic="Yaşam")

    assert tags == ["#coffee", "#breakfast"]

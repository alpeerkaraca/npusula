"""Unit tests for the uploaded-media pipeline.

Everything here runs without CLIP weights: limits, sampling, store and merge
rules are pure, and the model-dependent paths are asserted to *degrade* rather
than fail (mirroring the repo's "LLM unreachable -> deterministic fallback"
convention).
"""
from io import BytesIO
from pathlib import Path

import pytest
from PIL import Image

from backend.config import settings
from backend.schemas.media import MediaAnalysis
from backend.services.media_analysis import (
    MediaAnalysisStore,
    MediaAnalyzer,
    MediaTooLargeError,
    MediaTypeError,
    MediaUnavailableError,
    MediaValidationError,
    check_size,
    check_video_limits,
    choose_topic_source,
    detect_media_kind,
    evenly_spaced_timestamps,
    merge_tags,
    should_use_media_category,
    validate_image_bytes,
    VideoMeta,
)


def _media_analysis(category: str | None = "food_dining", confidence: float = 0.7) -> MediaAnalysis:
    return MediaAnalysis(
        media_kind="photo",
        filename="kahve.jpg",
        content_type="image/jpeg",
        size_bytes=1024,
        frames_analyzed=1,
        duration_seconds=None,
        width=32,
        height=24,
        topic=None,
        topic_confidence=0.2,
        canonical_category=category,
        category_confidence=confidence,
        category_margin=0.3,
        suggested_tags=["#kahve"],
        uncertain=category is None,
        model_name="test-model",
        embedding_dim=512,
    )


def _png_bytes(width: int = 32, height: int = 24) -> bytes:
    buffer = BytesIO()
    Image.new("RGB", (width, height), (200, 30, 30)).save(buffer, format="PNG")
    return buffer.getvalue()


def _jpeg_bytes() -> bytes:
    buffer = BytesIO()
    Image.new("RGB", (40, 40), (10, 10, 200)).save(buffer, format="JPEG")
    return buffer.getvalue()


# --- media kind detection -------------------------------------------------
def test_detect_media_kind_accepts_supported_types():
    assert detect_media_kind("tatil.jpg", "image/jpeg") == "photo"
    assert detect_media_kind("KAHVE.PNG", "image/png") == "photo"
    assert detect_media_kind("klip.mp4", "video/mp4") == "video"
    assert detect_media_kind("klip.MOV", "video/quicktime") == "video"


def test_detect_media_kind_rejects_other_types():
    with pytest.raises(MediaTypeError):
        detect_media_kind("belge.pdf", "application/pdf")
    with pytest.raises(MediaTypeError):
        detect_media_kind("arsiv.zip", "application/zip")
    with pytest.raises(MediaTypeError):
        detect_media_kind("", "")


# --- size limits ----------------------------------------------------------
def test_check_size_enforces_per_kind_limits():
    check_size("photo", int(settings.MAX_IMAGE_MB * 1024 * 1024))
    with pytest.raises(MediaTooLargeError):
        check_size("photo", int(settings.MAX_IMAGE_MB * 1024 * 1024) + 1)
    check_size("video", int(settings.MAX_VIDEO_MB * 1024 * 1024))
    with pytest.raises(MediaTooLargeError):
        check_size("video", int(settings.MAX_VIDEO_MB * 1024 * 1024) + 1)


def test_check_size_rejects_empty_payload():
    with pytest.raises(MediaValidationError):
        check_size("photo", 0)


def test_video_duration_limit():
    check_video_limits(VideoMeta(duration_seconds=settings.MAX_VIDEO_SECONDS, fps=30.0, width=640, height=480))
    with pytest.raises(MediaTooLargeError):
        check_video_limits(VideoMeta(duration_seconds=settings.MAX_VIDEO_SECONDS + 0.1, fps=30.0, width=640, height=480))
    with pytest.raises(MediaValidationError):
        check_video_limits(VideoMeta(duration_seconds=0.0, fps=30.0, width=640, height=480))


# --- frame sampling -------------------------------------------------------
def test_evenly_spaced_timestamps_uses_bucket_centres():
    stamps = evenly_spaced_timestamps(8.0, 4)
    assert stamps == [1.0, 3.0, 5.0, 7.0]
    # Centres never touch t=0 / t=duration, so the black first/last frame
    # problem cannot occur by construction.
    assert min(stamps) > 0.0
    assert max(stamps) < 8.0


def test_evenly_spaced_timestamps_is_deterministic_and_bounded():
    assert evenly_spaced_timestamps(3.7, 8) == evenly_spaced_timestamps(3.7, 8)
    stamps = evenly_spaced_timestamps(3.7, 8)
    assert len(stamps) == 8
    assert all(0.0 <= value <= 3.7 for value in stamps)


def test_evenly_spaced_timestamps_handles_degenerate_input():
    assert evenly_spaced_timestamps(0.0, 3) == [0.0, 0.0, 0.0]
    assert evenly_spaced_timestamps(float("nan"), 2) == [0.0, 0.0]
    assert evenly_spaced_timestamps(10.0, 0) == []


# --- escalation and merge rules ------------------------------------------
def test_choose_topic_source_prefers_confident_text_then_media_then_judge():
    assert choose_topic_source(0.40, 0.25, media_topic_confident=True) == "text"
    assert choose_topic_source(0.05, 0.25, media_topic_confident=True) == "media"
    assert choose_topic_source(0.05, 0.25, media_topic_confident=False) == "judge"


def test_should_use_media_category_only_when_text_matched_nothing():
    # 0.30 is the "no keyword matched" confidence in canonical_taxonomy.
    assert should_use_media_category(0.30, media_category_confident=True) is True
    assert should_use_media_category(0.65, media_category_confident=True) is False
    assert should_use_media_category(0.30, media_category_confident=False) is False


def test_merge_tags_prioritises_media_and_deduplicates():
    merged = merge_tags(
        media_tags=["#kahve", "#yaşam"],
        retrieved_tags=["#lifestyle", "#kahve"],
        fallback_tags=["#teknoloji", "#ilham"],
        limit=4,
    )
    assert merged == ["#kahve", "#yaşam", "#lifestyle", "#teknoloji"]


def test_merge_tags_respects_existing_three_tag_cap():
    merged = merge_tags(["#kahve"], ["#lifestyle"], ["#ilham"], limit=3)
    assert merged == ["#kahve", "#lifestyle", "#ilham"]
    assert len(merge_tags(["a"], ["b"], ["c"], limit=3)) == 3


def test_merge_tags_normalises_missing_hash_and_empty_values():
    merged = merge_tags(["kahve", "  ", ""], ["#KAHVE"], [], limit=3)
    assert merged == ["#kahve"]


# --- image validation -----------------------------------------------------
def test_validate_image_bytes_accepts_png_and_jpeg():
    assert validate_image_bytes(_png_bytes(32, 24))[:2] == (32, 24)
    assert validate_image_bytes(_jpeg_bytes())[2] == "JPEG"


def test_validate_image_bytes_rejects_non_image_payloads():
    with pytest.raises(MediaValidationError):
        validate_image_bytes(b"bu bir metin dosyasi, gorsel degil")


# --- store ----------------------------------------------------------------
def test_store_round_trips_analysis_and_mints_media_id():
    store = MediaAnalysisStore(ttl_seconds=60)
    record = store.put(_media_analysis())
    assert record.media_id
    fetched = store.get(record.media_id)
    assert fetched is not None
    assert fetched.canonical_category == "food_dining"


def test_store_expires_entries_and_returns_none_for_unknown_ids():
    store = MediaAnalysisStore(ttl_seconds=-1)
    record = store.put(_media_analysis())
    assert store.get(record.media_id) is None
    assert store.get("yok-boyle-bir-id") is None


def test_store_evicts_oldest_when_full():
    store = MediaAnalysisStore(ttl_seconds=60, max_entries=2)
    first = store.put(_media_analysis())
    second = store.put(_media_analysis())
    third = store.put(_media_analysis())
    assert store.get(first.media_id) is None
    assert store.get(second.media_id) is not None
    assert store.get(third.media_id) is not None


# --- model-input override -------------------------------------------------
def test_media_category_override_rewrites_the_category_columns():
    """The image category must be applied directly, not through the keyword mapper.

    `classify_post_category` cannot round-trip every canonical name (gaming and
    art_design lose their keyword to a word-boundary rule), so the override
    writes the code itself. Layer A has no time-interaction columns any more, so
    the override only has to keep the category columns consistent.
    """
    import pandas as pd

    from backend.services.canonical_taxonomy import CATEGORY_CODE_MAP
    from backend.services.recommendation import BASE_FEATURES, RecommendationService

    service = RecommendationService(model_path=Path("artifacts/.training-placeholder.txt"))
    features = pd.DataFrame([{
        "published_at_utc": "2016-01-01T12:00:00Z",
        "title": "bugün çok güzeldi",
        "tags": [],
        "media_type": "photo",
        "timezone_basis": "source_offset",
    }])
    X = service._prepare_features(features)

    assert set(X.columns) == set(BASE_FEATURES)
    assert "cat_x_hour" not in X.columns and "hour" not in X.columns

    assert RecommendationService._apply_media_category(X, None) is False
    assert RecommendationService._apply_media_category(X, _media_analysis("food_dining")) is True

    expected = float(CATEGORY_CODE_MAP["food_dining"])
    assert X["primary_cat_code"].iloc[0] == expected
    assert X["primary_cat_confidence"].iloc[0] == _media_analysis("food_dining").category_confidence

    # An uncertain analysis (no category) must leave the row untouched.
    assert RecommendationService._apply_media_category(X, _media_analysis(None)) is False


# --- API integration ------------------------------------------------------
def test_media_api_rejects_type_and_size_before_touching_the_model():
    """Validation runs ahead of model loading, so this passes without weights."""
    from fastapi.testclient import TestClient

    from backend.app import app

    client = TestClient(app)  # no lifespan: no model load, no dataset read
    response = client.post(
        "/api/media/analyze", files={"file": ("belge.pdf", b"%PDF-1.4", "application/pdf")}
    )
    assert response.status_code == 415

    oversized = b"\xff\xd8\xff" + b"0" * (int(settings.MAX_IMAGE_MB * 1024 * 1024) + 10)
    response = client.post(
        "/api/media/analyze", files={"file": ("buyuk.jpg", oversized, "image/jpeg")}
    )
    assert response.status_code == 413
    assert "10 MB" in response.json()["detail"]


def test_media_api_analyzes_upload_and_feeds_the_advisor():
    from fastapi.testclient import TestClient

    from backend.app import app

    with TestClient(app) as client:
        if not client.get("/api/health").json().get("media_analyzer_ready"):
            pytest.skip("CLIP weights are not available in this environment")

        response = client.post(
            "/api/media/analyze", files={"file": ("ornek.png", _png_bytes(64, 64), "image/png")}
        )
        assert response.status_code == 200
        payload = response.json()
        assert payload["media_kind"] == "photo"
        assert payload["frames_analyzed"] == 1
        assert payload["embedding_dim"] == 512

        request = {
            "user_id": "31253@N15",
            "idea": "bugün çok güzeldi",
            "media_type": "photo",
        }
        with_media = client.post(
            "/api/recommend/advisor", json={**request, "media_id": payload["media_id"]}
        )
        assert with_media.status_code == 200
        assert with_media.json()["media_analysis"]["media_id"] == payload["media_id"]

        # An unknown id degrades to the text-only path instead of failing.
        unknown = client.post(
            "/api/recommend/advisor", json={**request, "media_id": "bilinmeyen-id"}
        )
        assert unknown.status_code == 200
        assert unknown.json()["media_analysis"] is None


# --- graceful degradation -------------------------------------------------
def test_analyzer_degrades_when_weights_are_unavailable(tmp_path: Path):
    analyzer = MediaAnalyzer(model_name="npusula/does-not-exist", cache_dir=tmp_path)
    assert analyzer.warm_up() is False
    assert analyzer.is_ready is False
    with pytest.raises(MediaUnavailableError):
        analyzer.analyze(filename="kahve.jpg", content_type="image/jpeg", data=_jpeg_bytes())

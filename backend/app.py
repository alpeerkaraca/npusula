"""FastAPI application providing EnPusula backend services and API contracts."""
from contextlib import asynccontextmanager
import logging
import time
from typing import Any
from fastapi import FastAPI, File, HTTPException, Request, UploadFile, status
from fastapi.middleware.cors import CORSMiddleware

from backend.adapters.repository import PostRepository, UserRepository
from backend.adapters.storage import QdrantPostStore
from backend.logging_setup import setup_logging
from backend.schemas.media import MediaAnalysisResponse
from backend.schemas.profile import ProfileDecisionRequest, ProfileStatus
from backend.schemas.recommendation import (
    AdvisorRequest,
    AdvisorResponse,
    ModelMetricsResponse,
    QuickRecommendationResponse,
)
from backend.services.advisor import AdvisorService
from backend.services.device import device_manager
from backend.services.media_analysis import (
    MediaAnalysisStore,
    MediaAnalyzer,
    MediaError,
    detect_media_kind,
    read_upload_capped,
    size_limit_bytes,
)
from backend.services.profile import ProfileService
from backend.services.recommendation import RecommendationService
from backend.services.retrieval import RetrievalService

setup_logging()
logger = logging.getLogger("backend.app")

# Initialize repositories and services
post_repo = PostRepository()
user_repo = UserRepository()
profile_service = ProfileService()
retrieval_service = RetrievalService()
recommendation_service = RecommendationService()
media_analyzer = MediaAnalyzer()
media_store = MediaAnalysisStore()

advisor_service = AdvisorService(
    recommendation_service=recommendation_service,
    retrieval_service=retrieval_service,
    profile_service=profile_service,
    user_repo=user_repo,
    post_repo=post_repo,
    media_store=media_store,
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Train or load model artifact on startup
    df = post_repo.get_df()
    if not df.empty:
        recommendation_service.train_or_load(df)
        logger.info("startup complete: recommendation service ready (rows=%d)", len(df))
    else:
        logger.warning("startup: processed dataset is empty; model is unavailable")
    # Media analysis is optional by design: a missing checkpoint logs a warning
    # and /api/media/analyze answers 503, while the text-only advisor path (and
    # therefore the demo) keeps working.
    if media_analyzer.warm_up():
        logger.info("startup complete: media analyzer ready")
    else:
        logger.warning("startup: media analyzer unavailable; /api/media/analyze will answer 503")
    yield
    logger.info("shutdown complete")


app = FastAPI(
    title="EnPusula API",
    description="Intelligent Posting Time Recommendation & Profile Drift Advisor for EnSosyal",
    version="0.1.0",
    lifespan=lifespan,
)

# Enable CORS for frontend integration
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def log_requests(request: Request, call_next):
    """One INFO line per request with status and duration."""
    started = time.perf_counter()
    response = await call_next(request)
    duration_ms = (time.perf_counter() - started) * 1000.0
    logger.info(
        "%s %s %d %.0fms",
        request.method, request.url.path, response.status_code, duration_ms,
    )
    return response


@app.get("/api/health")
def get_health() -> dict[str, Any]:
    """Health check endpoint validating backend, vector database, and GPU acceleration."""
    qdrant_healthy = retrieval_service.store.is_healthy()
    gpu_info = device_manager.get_info()
    return {
        "status": "ok",
        "version": "0.1.0",
        "qdrant_connected": qdrant_healthy,
        "model_ready": recommendation_service.model is not None,
        "media_analyzer_ready": media_analyzer.is_ready,
        "gpu": gpu_info,
        "advisor_model": "google/gemma-4-E4B-it",
    }


@app.get("/api/demo-users")
def get_demo_users() -> list[dict[str, Any]]:
    """Returns the three curated demo accounts (aligned, drift, cold-start)."""
    return user_repo.get_demo_users()


@app.get("/api/profile/{user_id}", response_model=ProfileStatus)
def get_user_profile(user_id: str) -> ProfileStatus:
    """Returns declared vs behavioral profile and drift question if detected."""
    declared = user_repo.get_declared_profile(user_id)
    user_posts = post_repo.get_user_history(user_id)
    behavioral = profile_service.compute_behavioral_profile(user_id, user_posts)
    return profile_service.get_profile_status(declared, behavioral)


@app.post("/api/profile/{user_id}/decision", response_model=ProfileStatus)
def record_profile_decision(user_id: str, payload: ProfileDecisionRequest) -> ProfileStatus:
    """Records user's accept/decline response to a profile drift notification."""
    profile_service.record_decision(user_id, accept=payload.accept)
    declared = user_repo.get_declared_profile(user_id)
    user_posts = post_repo.get_user_history(user_id)
    behavioral = profile_service.compute_behavioral_profile(user_id, user_posts)
    return profile_service.get_profile_status(declared, behavioral)


@app.get("/api/recommend/quick/{user_id}", response_model=QuickRecommendationResponse)
def get_quick_recommendation(user_id: str) -> QuickRecommendationResponse:
    """Returns instant top-3 posting time recommendations for the user's active topic."""
    return advisor_service.get_quick_recommendation(user_id)


@app.post("/api/recommend/advisor", response_model=AdvisorResponse)
def get_advisor_recommendation(payload: AdvisorRequest) -> AdvisorResponse:
    """Full advisor pipeline: topic inference, slot scoring, Qdrant retrieval, and Turkish explanation."""
    return advisor_service.advise(payload)


@app.get("/api/model/metrics", response_model=ModelMetricsResponse)
def get_model_metrics() -> ModelMetricsResponse:
    """Returns offline test evaluation metrics and top feature importances."""
    return recommendation_service.get_metrics()


@app.post("/api/media/analyze", response_model=MediaAnalysisResponse)
def analyze_media(file: UploadFile = File(...)) -> MediaAnalysisResponse:
    """Analyses an uploaded photo or video: topic, canonical category, hashtags.

    This lives on its own endpoint because `/api/recommend/advisor` is a strict
    JSON contract that rejects unexpected fields; the returned `media_id` is
    passed back on the advisor request instead. Uncertain analyses carry
    `topic`/`canonical_category` as null rather than a guessed label.
    """
    filename = file.filename or ""
    content_type = file.content_type or ""
    try:
        kind = detect_media_kind(filename, content_type)
        data = read_upload_capped(file.file, size_limit_bytes(kind))
        analysis = media_analyzer.analyze(
            filename=filename, content_type=content_type, data=data
        )
    except MediaError as exc:
        logger.info("media analysis rejected: status=%s reason=%s", exc.status_code, exc.message)
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc
    finally:
        file.file.close()

    record = media_store.put(analysis)
    logger.info(
        "media analyzed: media_id=%s kind=%s frames=%d category=%s topic=%s uncertain=%s",
        record.media_id, record.media_kind, record.frames_analyzed,
        record.canonical_category, record.topic, record.uncertain,
    )
    return record

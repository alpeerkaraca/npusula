"""FastAPI application providing NPusula backend services and API contracts."""
from contextlib import asynccontextmanager
import logging
import time
from typing import Any
from uuid import uuid4
from fastapi import FastAPI, File, HTTPException, Request, UploadFile, status
from fastapi.middleware.cors import CORSMiddleware

from backend.adapters.db import init_db, migrate_from_json_if_needed
from backend.adapters.repository import (
    PostRepository,
    SavedContentRepository,
    UserRepository,
    _read_json_dict,
)
from backend.adapters.storage import QdrantPostStore
from backend.config import settings
from backend.logging_setup import setup_logging
from backend.schemas.media import MediaAnalysisResponse
from backend.schemas.profile import (
    DeclaredProfile,
    DeclaredTopicsRequest,
    ProfileDecisionRequest,
    ProfileStatus,
)
from backend.schemas.saved import (
    DraftRequest,
    DraftResponse,
    PlanRequest,
    PlanResponse,
)
from backend.schemas.recommendation import (
    AdvisorRequest,
    AdvisorResponse,
    ModelMetricsResponse,
    QuickRecommendationResponse,
)
from backend.schemas.sample_user import SampleUser, SampleUserList
from backend.services.advisor import AdvisorService, history_depth_name
from backend.services.artifact_sync import sync_artifacts_if_outdated
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
saved_repo = SavedContentRepository()
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
    # Query Nextcloud for artifact freshness and update if any are outdated
    if settings.AUTO_SYNC_ARTIFACTS_ON_STARTUP:
        try:
            sync_artifacts_if_outdated()
        except Exception as exc:
            logger.warning("runtime artifact sync skipped due to error: %s", exc)

    # Initialize SQLite database schema and migrate legacy JSON state if needed
    init_db(settings.SQLITE_DB_PATH)
    migrate_from_json_if_needed(settings.SQLITE_DB_PATH)

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
    title="NPusula API",
    description="Intelligent Posting Time Recommendation & Profile Drift Advisor",
    version="0.1.0",
    lifespan=lifespan,
)

# CORS for frontend integration. `allow_credentials` stays off: a wildcard
# origin with credentials is invalid per the CORS spec and browsers reject it.
# The service is stateless and issues no cookies, and the dev server proxies
# /api same-origin, so nothing needs credentialed cross-origin access.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
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
        "advisor_model": settings.LLM_MODEL_NAME,
        "llm_model": settings.LLM_MODEL_NAME,
    }


@app.get("/api/demo-users")
def get_demo_users() -> list[dict[str, Any]]:
    """Returns the three curated demo accounts (aligned, drift, cold-start)."""
    return user_repo.get_demo_users()


@app.get("/api/sample-users", response_model=SampleUserList)
def get_sample_users() -> SampleUserList:
    """Selectable accounts spanning the history-depth range, for the UI picker.

    Depth is derived from the corpus row count rather than ProfileService's
    ``evidence_post_count``: that one is capped at 30 (it reads the 30 most
    recent posts), so every account with real history reports
    ``medium_history`` and the picker could not tell them apart.
    """
    curated = _read_json_dict(settings.SAMPLE_USERS_PATH).get("users", [])
    user_ids = [entry for entry in curated if isinstance(entry, str)]
    counts = post_repo.get_user_post_counts(user_ids)
    return SampleUserList(
        users=[
            SampleUser(
                user_id=user_id,
                post_count=counts.get(user_id, 0),
                history_depth=history_depth_name(counts.get(user_id, 0)),
            )
            for user_id in user_ids
        ]
    )


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


@app.put("/api/profile/{user_id}/interests", response_model=DeclaredProfile)
def put_user_interests(
    user_id: str, payload: DeclaredTopicsRequest
) -> DeclaredProfile:
    """Stores the interest topics the setup wizard collected for this user.

    Topics arrive already mapped to the canonical vocabulary. Like every other
    profile route this trusts the caller-supplied `user_id`, because the service
    has no authentication; exposing it publicly requires adding one first.
    """
    user_repo.update_user_declared_topics(user_id, payload.topics)
    logger.info(
        "declared topics stored: user_id=%s topics=%s", user_id, payload.topics
    )
    return user_repo.get_declared_profile(user_id)


@app.post("/api/plans", response_model=PlanResponse)
def create_plan(payload: PlanRequest) -> PlanResponse:
    """Records content the user attached to a recommended window.

    This stores intent only: there is no scheduler, publish permission or
    notification behind it, so the response reports `status="saved"` and never
    claims the post was scheduled or published.
    """
    plan_id = f"plan-{uuid4().hex[:12]}"
    saved_repo.put(plan_id, {"kind": "plan", **payload.model_dump()})
    logger.info("plan saved: id=%s slot_id=%s", plan_id, payload.slot_id)
    return PlanResponse(
        id=plan_id,
        slot_id=payload.slot_id,
        starts_at=payload.starts_at,
        status="saved",
    )


@app.post("/api/drafts", response_model=DraftResponse)
def save_draft(payload: DraftRequest) -> DraftResponse:
    """Stores text the user wants carried into the composer. Does not post it."""
    draft_id = f"draft-{uuid4().hex[:12]}"
    saved_repo.put(draft_id, {"kind": "draft", **payload.model_dump()})
    logger.info("draft saved: id=%s chars=%d", draft_id, len(payload.text))
    return DraftResponse(id=draft_id, text=payload.text, format=payload.format)


@app.get("/api/recommend/quick/{user_id}", response_model=QuickRecommendationResponse)
def get_quick_recommendation(
    user_id: str,
    timezone: str | None = None,
    utc_offset_minutes: int | None = None,
) -> QuickRecommendationResponse:
    """Returns the supported sharing windows for the user's active topic.

    Callers should pass their IANA `timezone` (or a fixed offset); without it the
    windows are computed in UTC and the response says so (`timezone_basis`).
    """
    return advisor_service.get_quick_recommendation(
        user_id, timezone_name=timezone, utc_offset_minutes=utc_offset_minutes
    )


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

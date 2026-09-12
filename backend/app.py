"""FastAPI application providing EnPusula backend services and API contracts."""
from contextlib import asynccontextmanager
from typing import Any
from fastapi import FastAPI, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware

from backend.adapters.repository import PostRepository, UserRepository
from backend.adapters.storage import QdrantPostStore
from backend.schemas.profile import ProfileDecisionRequest, ProfileStatus
from backend.schemas.recommendation import (
    AdvisorRequest,
    AdvisorResponse,
    ModelMetricsResponse,
    QuickRecommendationResponse,
)
from backend.services.advisor import AdvisorService
from backend.services.device import device_manager
from backend.services.profile import ProfileService
from backend.services.recommendation import RecommendationService
from backend.services.retrieval import RetrievalService

# Initialize repositories and services
post_repo = PostRepository()
user_repo = UserRepository()
profile_service = ProfileService()
retrieval_service = RetrievalService()
recommendation_service = RecommendationService()

advisor_service = AdvisorService(
    recommendation_service=recommendation_service,
    retrieval_service=retrieval_service,
    profile_service=profile_service,
    user_repo=user_repo,
    post_repo=post_repo,
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Train or load model artifact on startup
    df = post_repo.get_df()
    if not df.empty:
        recommendation_service.train_or_load(df)
        print("RecommendationService initialized and trained.")
    yield


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

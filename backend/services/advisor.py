"""Danisman (Advisor) orchestrator combining recommendations, retrieval, and explanations."""
from datetime import datetime
import uuid

from fastapi import HTTPException

from backend.adapters.repository import PostRepository, UserRepository
from backend.schemas.post import MediaTypeEnum
from backend.schemas.recommendation import (
    AdvisorRequest,
    AdvisorResponse,
    CandidateSlot,
    QuickRecommendationResponse,
)
from backend.services.gemma_advisor import GemmaAdvisorEngine, format_slot_turkish
try:
    from backend.services.moderation import GemmaModerationGuardrail
except ImportError:
    GemmaModerationGuardrail = None
from backend.services.profile import ProfileService
from backend.services.recommendation import RecommendationService
from backend.services.retrieval import RetrievalService
from backend.services.canonical_taxonomy import classify_post_category
from backend.services.tag_taxonomy import align_tags


HISTORY_DEPTH_NAMES = {
    0: "cold_start",
    1: "very_low_history",
    2: "low_history",
    3: "medium_history",
    4: "high_history",
}


def history_depth_name(evidence_post_count: int) -> str:
    if evidence_post_count == 0:
        return HISTORY_DEPTH_NAMES[0]
    if evidence_post_count <= 5:
        return HISTORY_DEPTH_NAMES[1]
    if evidence_post_count <= 20:
        return HISTORY_DEPTH_NAMES[2]
    if evidence_post_count <= 100:
        return HISTORY_DEPTH_NAMES[3]
    return HISTORY_DEPTH_NAMES[4]


class AdvisorService:
    """Orchestrates end-to-end advice: topic inference, slot ranking, similar posts, and explanation."""

    def __init__(
        self,
        recommendation_service: RecommendationService,
        retrieval_service: RetrievalService,
        profile_service: ProfileService,
        user_repo: UserRepository,
        post_repo: PostRepository,
        gemma_advisor: GemmaAdvisorEngine | None = None,
        moderation_guardrail: GemmaModerationGuardrail | None = None,
    ):
        self.rec_service = recommendation_service
        self.retrieval_service = retrieval_service
        self.profile_service = profile_service
        self.user_repo = user_repo
        self.post_repo = post_repo
        self.gemma_advisor = gemma_advisor or GemmaAdvisorEngine()
        self.moderation = moderation_guardrail or (GemmaModerationGuardrail() if GemmaModerationGuardrail is not None else None)

    def get_quick_recommendation(self, user_id: str, days_ahead: int = 7) -> QuickRecommendationResponse:
        """Generates quick recommendations for the user's active topic."""
        user_posts = self.post_repo.get_user_history(user_id)
        declared = self.user_repo.get_declared_profile(user_id)
        behavioral = self.profile_service.compute_behavioral_profile(user_id, user_posts)
        status = self.profile_service.get_profile_status(declared, behavioral)

        active_topic = status.active_recommendation_topics[0].topic
        is_cold = behavioral.evidence_post_count == 0

        # Prior mean calculation
        if not user_posts.empty and "user_popularity_mean_prior" in user_posts.columns:
            prior_mean = float(user_posts["user_popularity_mean_prior"].iloc[-1])
        else:
            prior_mean = 5.8

        slots = self.rec_service.recommend_slots(
            user_prior_mean=prior_mean,
            user_post_count=behavioral.evidence_post_count,
            title="",
            tags=[f"#{active_topic.replace(' ', '')}"],
            media_type=MediaTypeEnum.PHOTO,
            topic=active_topic,
            days_ahead=days_ahead,
            top_k=3,
        )

        s1_str = format_slot_turkish(slots[0])
        s2_str = format_slot_turkish(slots[1]) if len(slots) > 1 else ""
        s3_str = format_slot_turkish(slots[2]) if len(slots) > 2 else ""

        if is_cold:
            explanation = (
                f"Henüz geçmiş paylaşımın bulunmadığı için {active_topic} kategorisinin "
                f"en yüksek etkileşim alan saatlerine göre planlandı. En güçlü zaman: {s1_str}."
            )
        else:
            explanation = (
                f"{active_topic} odaklı paylaşımlarınız için en yüksek potansiyele sahip zaman {s1_str}. "
                f"Alternatif olarak {s2_str} ve {s3_str} değerlendirilebilir."
            )

        return QuickRecommendationResponse(
            user_id=user_id,
            active_topic=active_topic,
            slots=slots,
            cold_start=is_cold,
            explanation=explanation,
        )

    def advise(self, request: AdvisorRequest) -> AdvisorResponse:
        """Processes user idea, retrieves similar posts, ranks candidate slots, and formats explanation."""
        req_id = f"req-{uuid.uuid4().hex[:8]}"

        # 0. Content safety & policy guardrail (Gemma 4 Shield Guardrail)
        # mod_result = self.moderation.evaluate(request.idea)

        # 1. Get user context
        user_posts = self.post_repo.get_user_history(request.user_id)
        behavioral = self.profile_service.compute_behavioral_profile(request.user_id, user_posts)
        declared = self.user_repo.get_declared_profile(request.user_id)
        if behavioral.evidence_post_count > 0 and behavioral.top_topic:
            fallback_topic = behavioral.top_topic
        elif declared.declared_topics:
            fallback_topic = declared.declared_topics[0]
        else:
            fallback_topic = "Teknoloji Trendleri"

        # 2. Infer topic with confidence threshold & profile fallback
        inferred_topic = self.profile_service.classify_text_topic(request.idea, fallback_topic=fallback_topic)
        category_result = classify_post_category(request.idea, None, None, None)
        primary_category = str(category_result["primary_category"])

        if not user_posts.empty and "user_popularity_mean_prior" in user_posts.columns:
            prior_mean = float(user_posts["user_popularity_mean_prior"].iloc[-1])
        else:
            prior_mean = 5.8

        # 3. Retrieve similar high-performing posts from Qdrant
        similar_posts = self.retrieval_service.search_similar_posts(
            topic=request.idea,
            limit=5,
            category_filter=primary_category,
        )

        # 4. Extract top weighted hashtags (topic-aware & safe)
        suggested_tags = self.retrieval_service.extract_top_tags(similar_posts, top_k=3, topic=inferred_topic)
        aligned_tags = align_tags(suggested_tags, context_category=primary_category)
        accepted_tags = [f"#{tag}" for tag in aligned_tags["accepted_tags"]]
        rejected_tags = [
            f"#{tag}"
            for tag in (
                aligned_tags["generic_tags"]
                + aligned_tags["rejected_tags"]
                + aligned_tags["nsfw_filtered_tags"]
            )
        ]

        # 5. Score candidate slots (using GPU Tabular NN + LightGBM ensemble)
        slots = self.rec_service.recommend_slots(
            user_prior_mean=prior_mean,
            user_post_count=behavioral.evidence_post_count,
            title=request.idea,
            tags=suggested_tags,
            media_type=request.media_type,
            topic=inferred_topic,
            days_ahead=7,
            top_k=3,
        )

        # 6. Generate Google Gemma 4 strategic Turkish explanation
        explanation = self.gemma_advisor.generate_explanation(
            idea=request.idea,
            topic=inferred_topic,
            media_type=request.media_type,
            slots=slots,
            suggested_tags=suggested_tags,
            similar_posts=similar_posts,
        )

        return AdvisorResponse(
            request_id=req_id,
            topic=inferred_topic,
            primary_category=primary_category,
            recommendations=slots,
            accepted_tags=accepted_tags,
            rejected_tags=rejected_tags,
            suggested_tags=suggested_tags,
            explanation=explanation,
            similar_posts=similar_posts,
            history_depth=history_depth_name(behavioral.evidence_post_count),
            confidence_level=slots[0].confidence_level if slots else "Düşük",
            model_version="lgbm-m5-residual + google/gemma-4-E4B-it",
            data_source="SMPD benchmark & EnSosyal demo",
            service_mode="deep_advisor",
        )

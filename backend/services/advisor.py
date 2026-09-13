"""Danisman (Advisor) orchestrator combining recommendations, retrieval, and explanations.

The advisor speaks the two-layer language: an informational base potential plus
recommended sharing **windows** with their observational evidence. It never
returns a single ranked "best hour" (plan §4.4 and §6.1).
"""
from __future__ import annotations

import logging
import uuid

from fastapi import HTTPException

from backend.adapters.repository import PostRepository, UserRepository
from backend.schemas.post import MediaTypeEnum
from backend.schemas.recommendation import (
    AdvisorRequest,
    AdvisorResponse,
    QuickRecommendationResponse,
    RecommendedWindow,
)
from backend.services.gemma_advisor import GemmaAdvisorEngine, format_window_turkish
try:
    from backend.services.moderation import GemmaModerationGuardrail
except ImportError:
    GemmaModerationGuardrail = None
from backend.services.profile import ProfileService
from backend.services.media_analysis import (
    TEXT_CATEGORY_NO_MATCH_CONFIDENCE,
    MediaAnalysisStore,
    choose_topic_source,
    merge_tags,
    should_use_media_category,
)
from backend.services.recommendation import RecommendationService, get_history_depth_code
from backend.services.retrieval import RetrievalService, TOPIC_DEFAULT_TAGS, is_clean_tag
from backend.services.canonical_taxonomy import classify_post_category
from backend.services.tag_taxonomy import align_tags

logger = logging.getLogger(__name__)


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


def _windows_sentence(windows: list[RecommendedWindow]) -> str:
    if not windows:
        return "pencere hesaplanamadı"
    return ", ".join(format_window_turkish(window) for window in windows[:3])


def dedupe_tags(tags: list[str]) -> list[str]:
    """De-duplicates hashtags case-insensitively, keeping the first occurrence.

    Retrieved tags and topic defaults overlap heavily, and reporting the same
    tag twice in `accepted_tags` would overstate how much evidence there is.
    """
    seen: set[str] = set()
    unique: list[str] = []
    for tag in tags:
        key = tag.lstrip("#").strip().lower()
        if not key or key in seen:
            continue
        seen.add(key)
        unique.append(tag)
    return unique


class AdvisorService:
    """Orchestrates end-to-end advice: topic inference, window scoring, similar posts, explanation."""

    def __init__(
        self,
        recommendation_service: RecommendationService,
        retrieval_service: RetrievalService,
        profile_service: ProfileService,
        user_repo: UserRepository,
        post_repo: PostRepository,
        gemma_advisor: GemmaAdvisorEngine | None = None,
        moderation_guardrail: GemmaModerationGuardrail | None = None,
        media_store: MediaAnalysisStore | None = None,
    ):
        self.rec_service = recommendation_service
        self.retrieval_service = retrieval_service
        self.profile_service = profile_service
        self.user_repo = user_repo
        self.post_repo = post_repo
        self.gemma_advisor = gemma_advisor or GemmaAdvisorEngine()
        self.moderation = moderation_guardrail or (GemmaModerationGuardrail() if GemmaModerationGuardrail is not None else None)
        self.media_store = media_store

    def get_quick_recommendation(
        self,
        user_id: str,
        days_ahead: int = 7,
        timezone_name: str | None = None,
        utc_offset_minutes: int | None = None,
    ) -> QuickRecommendationResponse:
        """Generates quick window recommendations for the user's active topic."""
        user_posts = self.post_repo.get_user_history(user_id)
        declared = self.user_repo.get_declared_profile(user_id)
        behavioral = self.profile_service.compute_behavioral_profile(user_id, user_posts)
        status = self.profile_service.get_profile_status(declared, behavioral)

        active_topic = status.active_recommendation_topics[0].topic
        is_cold = behavioral.evidence_post_count == 0

        if not user_posts.empty and "user_popularity_mean_prior" in user_posts.columns:
            prior_mean = float(user_posts["user_popularity_mean_prior"].iloc[-1])
        else:
            prior_mean = 5.8

        recommendation = self.rec_service.recommend_windows(
            user_prior_mean=prior_mean,
            user_post_count=behavioral.evidence_post_count,
            title="",
            tags=[f"#{active_topic.replace(' ', '')}"],
            media_type=MediaTypeEnum.PHOTO,
            topic=active_topic,
            days_ahead=days_ahead,
            max_windows=3,
            timezone_name=timezone_name,
            utc_offset_minutes=utc_offset_minutes,
        )

        windows_text = _windows_sentence(recommendation.windows)
        if recommendation.is_tie_or_broad_window:
            explanation = (
                f"{active_topic} içeriklerin için saat etkisi belirgin değil; "
                f"{windows_text} aralıklarından uygun olanı seçebilirsin. "
                f"Güven seviyesi: {recommendation.confidence_label}."
            )
        else:
            explanation = (
                f"Geçmiş gözlemlerde desteklenen pencere: {windows_text}. "
                f"Bu nedensel bir iddia değil, tarihsel gözlemsel bir sinyaldir. "
                f"Güven seviyesi: {recommendation.confidence_label}."
            )
        if recommendation.timezone_fallback:
            explanation += (
                " Saat dilimi bilgisi paylaşılmadığı için pencereler UTC'ye göre hesaplandı; "
                "yerel saat dilimini iletirsen öneri netleşir."
            )
        if is_cold:
            explanation += (
                " Henüz geçmiş paylaşımın bulunmadığı için içerik potansiyeli kategori "
                "ortalamasına dayanıyor."
            )

        return QuickRecommendationResponse(
            user_id=user_id,
            active_topic=active_topic,
            windows=recommendation.windows,
            cold_start=is_cold,
            confidence=recommendation.confidence,
            confidence_label=recommendation.confidence_label,
            timezone_basis=recommendation.timezone_basis,
            explanation=explanation,
        )

    def advise(self, request: AdvisorRequest) -> AdvisorResponse:
        """Processes the user idea, retrieves similar posts, scores local windows, explains."""
        req_id = f"req-{uuid.uuid4().hex[:8]}"

        # 0. Content safety & policy guardrail (Gemma 4 Shield Guardrail)
        # Confidence-gated: only decisive model confidence, obfuscated evasion,
        # or an LLM verdict can block; uncertain cases fail open to avoid
        # false positives on legitimate content.
        if self.moderation is not None:
            mod_result = self.moderation.evaluate(request.idea)
            if not mod_result.is_safe:
                logger.warning(
                    "guardrail blocked request: request_id=%s user=%s category=%s risk=%.2f",
                    req_id, request.user_id, mod_result.category, mod_result.risk_score,
                )
                raise HTTPException(status_code=400, detail=mod_result.reason)

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

        # 1b. Resolve an analysed upload, if the request references one.
        media = None
        if request.media_id:
            media = self.media_store.get(request.media_id) if self.media_store else None
            if media is None:
                logger.warning(
                    "advisor: media_id not found or expired (%s); continuing text-only",
                    request.media_id,
                )

        # 2. Infer topic. The TF-IDF classifier is only a fast confident path;
        # weak or zero matches are escalated to a confident image analysis and
        # then to the Gemma topic judge.
        inferred_topic, topic_sim = self.profile_service.classify_text_topic_confident(
            request.idea, fallback_topic=fallback_topic
        )
        topic_source = choose_topic_source(
            topic_sim,
            self.profile_service.CONFIDENT_SIM_THRESHOLD,
            media_topic_confident=bool(media is not None and media.topic),
        )
        if topic_source == "media" and media is not None and media.topic:
            inferred_topic = media.topic
        elif topic_source == "judge":
            llm_topic = self.gemma_advisor.classify_topic(
                request.idea, self.profile_service.topic_names
            )
            if llm_topic:
                inferred_topic = llm_topic

        category_result = classify_post_category(request.idea, None, None, None)
        primary_category = str(category_result["primary_category"])

        # The image category only overrides a text classification that matched
        # nothing at all; `media_context` is forwarded to window scoring only
        # when it was actually adopted.
        media_context = None
        if should_use_media_category(
            float(category_result["primary_cat_confidence"]),
            media_category_confident=bool(media is not None and media.canonical_category),
        ) and media is not None and media.canonical_category:
            primary_category = str(media.canonical_category)
            media_context = media

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

        # 4. Classify every candidate hashtag against this post's canonical
        #    category. Only aligned-semantic tags may be recommended; tags the
        #    dictionary does not know are reported as `unknown_tags` rather than
        #    being called irrelevant or silently dropped (plan §3.1.4 and §6.2).
        # Alignment needs a category we actually believe. When the text
        # classifier matched nothing (its no-match floor) and no image category
        # was adopted, `primary_category` is a fallback, not knowledge: a known
        # tag must then be reported as aligned-by-domain rather than mislabelled
        # `mismatched` against a category nobody asserted.
        text_category_confidence = float(category_result["primary_cat_confidence"])
        alignment_context: str | None = primary_category
        if media_context is None and text_category_confidence <= TEXT_CATEGORY_NO_MATCH_CONFIDENCE:
            alignment_context = None

        topic_defaults = TOPIC_DEFAULT_TAGS.get(inferred_topic, [])
        candidate_tags = dedupe_tags(
            self.retrieval_service.extract_top_tags(similar_posts, top_k=5, topic=inferred_topic)
            + topic_defaults
        )
        alignment = align_tags(candidate_tags, context_category=alignment_context)
        accepted_tags = [f"#{tag}" for tag in alignment["aligned_semantic"]]
        rejected_tags = [
            f"#{tag}" for tag in alignment["mismatched_semantic"] + alignment["nsfw_filtered"]
        ]
        unknown_tags = [f"#{tag}" for tag in alignment["unknown"]]

        suggested_tags = accepted_tags[:3]

        # 4b. Media-derived hashtags are verified against the category the image
        # itself supports (they come from the same analysis, so they are aligned
        # by construction unless the image disagrees with its own tags).
        if media is not None:
            media_tags = [tag for tag in media.suggested_tags if is_clean_tag(tag)]
            media_alignment = align_tags(
                media_tags, context_category=media.canonical_category or alignment_context
            )
            verified_media_tags = [f"#{tag}" for tag in media_alignment["aligned_semantic"]]
            suggested_tags = merge_tags(
                verified_media_tags,
                suggested_tags,
                [],
                limit=3,
            )

        # 5. Score the local 3-hour windows of the next 7 days (Layer A + Layer B)
        recommendation = self.rec_service.recommend_windows(
            user_prior_mean=prior_mean,
            user_post_count=behavioral.evidence_post_count,
            title=request.idea,
            tags=suggested_tags,
            media_type=request.media_type,
            topic=inferred_topic,
            days_ahead=7,
            max_windows=3,
            timezone_name=request.timezone,
            utc_offset_minutes=request.utc_offset_minutes,
            media_context=media_context,
        )

        # 6. Generate the Gemma 4 explanation under the mandatory wording rules
        explanation = self.gemma_advisor.generate_explanation(
            idea=request.idea,
            topic=inferred_topic,
            media_type=request.media_type,
            window_recommendation=recommendation,
            suggested_tags=suggested_tags,
            similar_posts=similar_posts,
        )

        if media_context is not None:
            category_confidence = float(media_context.category_confidence)
            category_is_fallback = False
        else:
            category_confidence = text_category_confidence
            category_is_fallback = text_category_confidence <= TEXT_CATEGORY_NO_MATCH_CONFIDENCE

        history_depth = history_depth_name(behavioral.evidence_post_count)
        logger.info(
            "advisor completed: request_id=%s user=%s topic=%s(%s) category=%s windows=%d "
            "confidence=%s tie=%s tz=%s similar=%d history_depth=%s media=%s",
            req_id, request.user_id, inferred_topic, topic_source, primary_category,
            len(recommendation.windows), recommendation.confidence,
            recommendation.is_tie_or_broad_window, recommendation.timezone_basis,
            len(similar_posts), history_depth,
            media.media_id if media is not None else "-",
        )
        return AdvisorResponse(
            request_id=req_id,
            topic=inferred_topic,
            primary_category=primary_category,
            primary_category_confidence=category_confidence,
            primary_category_is_fallback=category_is_fallback,
            windows=recommendation.windows,
            accepted_tags=accepted_tags,
            rejected_tags=rejected_tags,
            unknown_tags=unknown_tags,
            suggested_tags=suggested_tags,
            explanation=explanation,
            similar_posts=similar_posts,
            history_depth=history_depth,
            confidence_level=recommendation.confidence_label,
            confidence=recommendation.confidence,
            is_tie_or_broad_window=recommendation.is_tie_or_broad_window,
            timezone_basis=recommendation.timezone_basis,
            timezone_fallback=recommendation.timezone_fallback,
            model_version="base-potential-lgbm + time-lift-table + google/gemma-4-E4B-it",
            data_source="SMPD benchmark (observational) & EnSosyal demo",
            service_mode="deep_advisor",
            media_analysis=media,
        )


__all__ = ["AdvisorService", "history_depth_name", "HISTORY_DEPTH_NAMES", "get_history_depth_code"]

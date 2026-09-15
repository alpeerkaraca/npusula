"""Strategic LLM Advisor Engine for NPusula.

Produces the Turkish explanation that sits on top of the two-layer output:
Layer A (base potential) plus Layer B (observational time windows).

Mandatory wording rules:
- never state a causal claim about the hour,
- say so explicitly when confidence is low,
- speak of "geçmiş gözlemlerde desteklenen pencere",
- disclose a UTC fallback when the caller sent no timezone,
- suggest only semantically aligned hashtags.
"""
from __future__ import annotations

import logging
from typing import Any

import httpx

from backend.config import settings
from backend.prompts import build_advisor_prompt, build_topic_prompt, format_window_turkish
from backend.schemas.post import MediaTypeEnum
from backend.schemas.recommendation import SimilarPost, WindowRecommendation

logger = logging.getLogger(__name__)


def _format_window_sentence(windows: list) -> str:
    parts = [f"{format_window_turkish(w)}" for w in windows[:2]]
    return " veya ".join(parts) if parts else "uygun bir zaman aralığı"


class LLMAdvisorEngine:
    """Strategic LLM advisor engine for content advice, topic arbitration, and strategy explanation."""

    def __init__(
        self,
        model_name: str | None = None,
        api_url: str | None = None,
        timeout_seconds: float = settings.LLM_TIMEOUT_SECONDS,
    ):
        self.model_name = model_name or settings.LLM_MODEL_NAME
        self.api_url = api_url or settings.LLM_API_URL
        self.timeout = timeout_seconds

    def build_prompt(
        self,
        idea: str,
        topic: str,
        media_type: MediaTypeEnum,
        window_recommendation: WindowRecommendation,
        suggested_tags: list[str],
        similar_posts: list[SimilarPost],
    ) -> str:
        """Constructs an instruction-following prompt."""
        return build_advisor_prompt(
            idea=idea,
            topic=topic,
            media_type=media_type,
            window_recommendation=window_recommendation,
            suggested_tags=suggested_tags,
            similar_posts=similar_posts,
            population_mean=settings.BASE_POTENTIAL_MEAN,
        )

    def _payload(self, prompt: str, max_tokens: int) -> dict[str, Any]:
        """Request body with a per-call generation cap."""
        return {
            "model": self.model_name,
            "prompt": prompt,
            "stream": False,
            "think": settings.LLM_THINK,
            "options": {"num_predict": max_tokens, "temperature": 0},
        }

    def _post_generate(self, prompt: str, max_tokens: int) -> httpx.Response | None:
        """Posts one generation request, retrying intermittent 500s."""
        endpoint = f"{self.api_url.rstrip('/')}/api/generate"
        payload = self._payload(prompt, max_tokens)
        attempts = max(1, settings.LLM_RETRY_COUNT)
        with httpx.Client(timeout=self.timeout) as client:
            for attempt in range(attempts):
                try:
                    res = client.post(endpoint, json=payload)
                except Exception as exc:
                    logger.debug("llm call failed (attempt %d/%d): %s", attempt + 1, attempts, exc)
                    continue
                if res.status_code == 200:
                    return res
                logger.debug(
                    "llm returned status %d (attempt %d/%d)", res.status_code, attempt + 1, attempts
                )
        return None

    def classify_topic(self, idea: str, options: list[str]) -> str | None:
        """Asks the LLM to select the best topic for an idea when keyword overlap is ambiguous."""
        if not options:
            return None
        prompt = build_topic_prompt(idea, options)
        res = self._post_generate(prompt, max_tokens=settings.LLM_JUDGE_MAX_TOKENS)
        if res is None:
            return None
        try:
            raw = res.json().get("response", "").strip()
        except Exception:
            return None

        # Clean trailing punctuation and look for an exact or substring match
        cleaned = raw.strip().strip('"').strip("'").rstrip(".,;")
        for opt in options:
            if opt.lower() == cleaned.lower():
                return opt
        for opt in options:
            if opt.lower() in cleaned.lower():
                return opt

        logger.debug("llm topic classification '%s' did not match options %s", raw, options)
        return None

    def _generate_fallback(
        self,
        window_recommendation: WindowRecommendation,
        media_type: MediaTypeEnum,
        suggested_tags: list[str],
    ) -> str:
        """Deterministic fallback reproducing the required wording rules."""
        windows = window_recommendation.windows
        if not windows:
            return (
                "Bu içerik için önerilen paylaşım penceresi hesaplanamadı. "
                "Lütfen daha sonra tekrar deneyin."
            )

        media_value = media_type.value if hasattr(media_type, "value") else str(media_type)
        tip = (
            "Videonun ilk 3 saniyesinde merak uyandırıcı bir soru sorup görsel dinamizm sağlamak erişimi artırabilir."
            if media_value == "video"
            else "İlk görselde infografik veya net bir tipografi kullanarak kaydırma oranını artırabilirsiniz."
        )
        tags_str = ", ".join(suggested_tags) if suggested_tags else "doğrulanmış etiket bulunamadı"

        tz_note = (
            " Saat dilimi bilgisi paylaşılmadığı için pencereler UTC'ye göre hesaplandı; "
            "yerel saat diliminizi iletirseniz öneri netleşir."
            if window_recommendation.timezone_fallback
            else f" Pencereler yerel saatinize göre hesaplandı ({window_recommendation.timezone_label})."
        )

        if window_recommendation.is_tie_or_broad_window:
            options = " veya ".join(format_window_turkish(window) for window in windows[:2])
            return (
                "Bu içerik için saat etkisi belirgin değil. "
                f"{options} aralıklarından uygun olanı seçebilirsin. "
                f"Güven seviyesi: {window_recommendation.confidence_label} "
                f"(içerik potansiyeli {window_recommendation.base_potential:.2f})."
                f"{tz_note}"
            )

        best = windows[0]
        alternatives = ", ".join(format_window_turkish(window) for window in windows[1:])
        alternative_text = f" Alternatif olarak {alternatives} pencereleri değerlendirilebilir." if alternatives else ""
        return (
            f"Geçmiş gözlemlerde desteklenen pencere {format_window_turkish(best)} "
            f"(gözlemsel lift {best.observational_time_lift:+.2f}, destek: {best.support_post_count} gönderi / "
            f"{best.support_user_count} kullanıcı). Bu bir nedensellik iddiası değil, tarihsel gözlemsel bir sinyaldir. "
            f"İçerik potansiyeli {window_recommendation.base_potential:.2f}, güven seviyesi "
            f"{window_recommendation.confidence_label}.{alternative_text} "
            f"Doğrulanmış etiketler: {tags_str}. Strateji Önerisi: {tip}"
            f"{tz_note}"
        )

    def generate_explanation(
        self,
        idea: str,
        topic: str,
        media_type: MediaTypeEnum,
        window_recommendation: WindowRecommendation,
        suggested_tags: list[str],
        similar_posts: list[SimilarPost],
    ) -> str:
        """Produces strategic advice: calls the LLM, falls back deterministically on any failure."""
        fallback = self._generate_fallback(
            window_recommendation=window_recommendation,
            media_type=media_type,
            suggested_tags=suggested_tags,
        )

        try:
            prompt = self.build_prompt(
                idea=idea,
                topic=topic,
                media_type=media_type,
                window_recommendation=window_recommendation,
                suggested_tags=suggested_tags,
                similar_posts=similar_posts,
            )
            res = self._post_generate(prompt, max_tokens=settings.LLM_MAX_TOKENS)
            if res is not None and res.status_code == 200:
                text = (res.json().get("response") or "").strip()
                if text and len(text) >= 50:
                    return text
                logger.debug("llm explanation too short (%d chars); using fallback", len(text))
        except Exception as exc:
            logger.debug("llm explanation call failed: %s; using fallback", exc)

        return fallback


# Backward-compatible alias
GemmaAdvisorEngine = LLMAdvisorEngine

__all__ = ["LLMAdvisorEngine", "GemmaAdvisorEngine", "format_window_turkish"]

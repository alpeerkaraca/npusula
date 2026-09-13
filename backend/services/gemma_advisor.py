"""Gemma 4 Strategic Advisor Engine for EnPusula (google/gemma-4-E4B-it).

Generates actionable, strategic Turkish recommendations combining:
- Inferred content topic and media type
- Deep Tabular Neural Network / LightGBM slot predictions
- Qdrant retrieved high-popularity exemplars
"""
import logging
from typing import Any
import httpx

from backend.config import settings
from backend.schemas.post import MediaTypeEnum
from backend.schemas.recommendation import CandidateSlot, SimilarPost

logger = logging.getLogger(__name__)

TR_WEEKDAYS = [
    "Pazartesi",
    "Salı",
    "Çarşamba",
    "Perşembe",
    "Cuma",
    "Cumartesi",
    "Pazar",
]


def format_slot_turkish(slot: CandidateSlot) -> str:
    weekday_str = TR_WEEKDAYS[slot.weekday]
    hour_str = f"{slot.hour:02d}:00"
    return f"{weekday_str} {hour_str}"


class GemmaAdvisorEngine:
    """Strategic LLM advisor engine utilizing Google DeepMind Gemma 4 architecture."""

    def __init__(
        self,
        model_name: str | None = None,
        api_url: str | None = None,
        timeout_seconds: float = 15.0,
    ):
        self.model_name = model_name or settings.GEMMA_MODEL_NAME
        self.api_url = api_url or settings.GEMMA_API_URL
        self.timeout = timeout_seconds

    def build_prompt(
        self,
        idea: str,
        topic: str,
        media_type: MediaTypeEnum,
        slots: list[CandidateSlot],
        suggested_tags: list[str],
        similar_posts: list[SimilarPost],
    ) -> str:
        """Constructs a strict instruction-following prompt in Gemma 4 turn format."""
        s1 = format_slot_turkish(slots[0]) if len(slots) > 0 else "Belirlenemedi"
        s2 = format_slot_turkish(slots[1]) if len(slots) > 1 else ""
        s3 = format_slot_turkish(slots[2]) if len(slots) > 2 else ""

        tags_str = ", ".join(suggested_tags) if suggested_tags else "Genel"

        exemplar_summaries = []
        for i, post in enumerate(similar_posts[:3], 1):
            exemplar_summaries.append(
                f"{i}. [Skor: {post.popularity_score:.1f}] {post.title[:50]} (Etiketler: {', '.join(post.tags[:3])})"
            )
        exemplars_str = "\n".join(exemplar_summaries) if exemplar_summaries else "Benzer gönderi verisi mevcut."

        prompt = (
            f"<start_of_turn>user\n"
            f"Sen EnSosyal platformunun yapay zeka içerik ve paylaşım zamanı strateji danışmanısın (Gemma 4 Advisor).\n"
            f"Aşağıdaki içerik fikrini, kategori bilgisini, AMD Radeon RX 9070 XT üzerinde koşan derin öğrenme "
            f"modelimizin puanladığı aday zaman dilimlerini ve Qdrant vektör aramasından gelen en başarılı gönderileri analiz et.\n\n"
            f"İÇERİK BİLGİSİ:\n"
            f"- Fikir: {idea}\n"
            f"- Medya Türü: {media_type.value if hasattr(media_type, 'value') else media_type}\n"
            f"- Kategori: {topic}\n\n"
            f"EN İYİ ZAMAN DİLİMLERİ (Model Puanı):\n"
            f"- 1. Aday: {s1} (Skor: {slots[0].predicted_popularity:.2f})\n"
            f"- 2. Aday: {s2} (Skor: {slots[1].predicted_popularity if len(slots) > 1 else 0.0:.2f})\n"
            f"- 3. Aday: {s3} (Skor: {slots[2].predicted_popularity if len(slots) > 2 else 0.0:.2f})\n\n"
            f"BENZER BAŞARILI GÖNDERİLER:\n"
            f"{exemplars_str}\n"
            f"Önerilen Etiketler: {tags_str}\n\n"
            f"TALİMATLAR:\n"
            f"1. Açıklamanda mutlaka 'en güçlü aday' ifadesini kullanarak ilk adayı vurgula.\n"
            f"2. Alternatif adayları ve önerilen etiketleri belirt.\n"
            f"3. {media_type.value if hasattr(media_type, 'value') else media_type} formatına özel stratejik bir kanca (hook) veya içerik tavsiyesi ver.\n"
            f"4. Yanıtı net, profesyonel Türkçe ile tek bir akıcı paragrafta sun.<end_of_turn>\n"
            f"<start_of_turn>model\n"
        )
        return prompt

    def classify_topic(self, idea: str, options: list[str]) -> str | None:
        """Asks Gemma to pick the best topic for an idea.

        Used when the local TF-IDF topic classifier has zero vocabulary
        overlap and would fall back to an unrelated user profile topic.
        Returns None when the model is unreachable or its answer cannot be
        mapped to one of the given options (callers then keep their fallback).
        """
        topic_descriptions = {
            "Yapay Zeka": "yapay zeka, makine öğrenmesi, derin öğrenme, LLM, otomasyon",
            "Yazılım": "yazılım, programlama, web, mobil uygulama, geliştirme",
            "Teknoloji Trendleri": "donanım, cihazlar, elektronik, yeni teknolojiler",
            "Oyun": "video oyunları, konsol, espor, oyun içi içerik",
            "Eğitim": "ders, öğrenme, kurs, kitap, sınav, okul",
            "Finans": "borsa, yatırım, kripto, ekonomi, tasarruf",
            "Spor": "fiziksel aktivite, müsabaka, maç, antrenman, güreş, fitness",
            "Kültür-Sanat": "sanat, müzik, sinema, fotoğraf, sergi, edebiyat",
            "Girişimcilik": "startup, iş kurma, büyüme, yatırımcı",
            "Yaşam": "günlük yaşam, aile, yemek, seyahat, moda, sağlık, eğlence",
        }
        opts = "; ".join(f"{name} ({desc})" for name, desc in topic_descriptions.items() if name in options)
        prompt = (
            f"<start_of_turn>user\n"
            f"Sen EnSosyal platformunun içerik konu sınıflandırıcısısın.\n"
            f"Aşağıdaki içerik fikrini YALNIZCA şu konulardan birine ata:\n{opts}\n\n"
            f"Fikir: \"{idea}\"\n\n"
            f"TALİMAT: SADECE listedeki konu adlarından birini yanıtla, başka hiçbir metin ekleme.\n"
            f"<end_of_turn>\n"
            f"<start_of_turn>model\n"
        )
        try:
            endpoint = f"{self.api_url.rstrip('/')}/api/generate"
            with httpx.Client(timeout=self.timeout) as client:
                res = client.post(
                    endpoint,
                    json={"model": self.model_name, "prompt": prompt, "stream": False},
                )
                if res.status_code != 200:
                    logger.debug("gemma topic classification returned status %d", res.status_code)
                    return None
                response_text = (res.json().get("response") or "").strip()
        except Exception as e:
            logger.debug("gemma topic classification call failed: %s", e)
            return None

        for option in options:
            if option.lower() in response_text.lower():
                return option
        return None

    def _generate_fallback(
        self,
        idea: str,
        topic: str,
        media_type: MediaTypeEnum,
        slots: list[CandidateSlot],
        suggested_tags: list[str],
    ) -> str:
        """Deterministic, highly tailored fallback reproducing Gemma 4 instruction output."""
        s1 = format_slot_turkish(slots[0])
        s2 = format_slot_turkish(slots[1]) if len(slots) > 1 else ""
        s3 = format_slot_turkish(slots[2]) if len(slots) > 2 else ""
        tags_str = ", ".join(suggested_tags)

        m_type = media_type.value if hasattr(media_type, "value") else str(media_type)
        if m_type == "video":
            tip = "Videonun ilk 3 saniyesinde merak uyandırıcı bir soru sorup görsel dinamizm sağlamak erişimi katlayacaktır."
        else:
            tip = "İlk görselde infografik veya net bir tipografi kullanarak kaydırma oranını artırabilirsiniz."

        return (
            f"Bu fikir için en güçlü aday {s1} (tahmini skor: {slots[0].predicted_popularity:.2f}). "
            f"Alternatif olarak {s2} ve {s3} değerlendirilebilir. "
            f"Benzer başarılı paylaşımlarda {tags_str} etiketleri öne çıkıyor. "
            f"Strateji Önerisi: {tip}"
        )

    def generate_explanation(
        self,
        idea: str,
        topic: str,
        media_type: MediaTypeEnum,
        slots: list[CandidateSlot],
        suggested_tags: list[str],
        similar_posts: list[SimilarPost],
    ) -> str:
        """Calls Gemma 4 endpoint if available, falling back safely to deterministic synthesis."""
        fallback = self._generate_fallback(
            idea=idea,
            topic=topic,
            media_type=media_type,
            slots=slots,
            suggested_tags=suggested_tags,
        )

        try:
            prompt = self.build_prompt(
                idea=idea,
                topic=topic,
                media_type=media_type,
                slots=slots,
                suggested_tags=suggested_tags,
                similar_posts=similar_posts,
            )
            # Try contacting local Ollama or OpenAI-compatible endpoint
            endpoint = f"{self.api_url.rstrip('/')}/api/generate"
            with httpx.Client(timeout=self.timeout) as client:
                res = client.post(
                    endpoint,
                    json={
                        "model": self.model_name,
                        "prompt": prompt,
                        "stream": False,
                    },
                )
                if res.status_code == 200:
                    data = res.json()
                    text = data.get("response", "").strip()
                    # Accept any substantive answer instead of requiring one
                    # exact phrase; local generation often rephrases.
                    if text and len(text) >= 50:
                        return text
                    logger.debug("gemma explanation too short (%d chars); using fallback", len(text))
        except Exception as e:
            logger.debug("gemma explanation call failed: %s; using fallback", e)

        return fallback

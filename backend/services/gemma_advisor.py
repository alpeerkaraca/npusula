"""Gemma 4 Strategic Advisor Engine for NPusula (google/gemma-4-E4B-it).

Produces the Turkish explanation that sits on top of the two-layer output:
Layer A (base potential) plus Layer B (observational time windows).

Mandatory wording rules (plan §6.2) — the model is instructed, and the
deterministic fallback is written the same way:
- never state a causal claim about the hour,
- say so explicitly when confidence is low,
- speak of "geçmiş gözlemlerde desteklenen pencere",
- disclose a UTC fallback when the caller sent no timezone,
- suggest only semantically aligned hashtags.
"""
import logging

import httpx

from backend.config import settings
from backend.schemas.post import MediaTypeEnum
from backend.schemas.recommendation import RecommendedWindow, SimilarPost, WindowRecommendation

logger = logging.getLogger(__name__)


def format_window_turkish(window: RecommendedWindow) -> str:
    """Formats a window as ``Salı 18.00–21.00``."""
    return f"{window.weekday} {window.time_range_local}"


def _window_line(window: RecommendedWindow, index: int) -> str:
    support = f"{window.support_post_count} gönderi/{window.support_user_count} kullanıcı"
    lift = f"{window.observational_time_lift:+.2f}"
    return (
        f"- {index}. Pencere: {format_window_turkish(window)} "
        f"(gözlemsel lift {lift}, destek {support}, kanıt: {window.evidence_level})"
    )


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
        window_recommendation: WindowRecommendation,
        suggested_tags: list[str],
        similar_posts: list[SimilarPost],
    ) -> str:
        """Constructs a strict instruction-following prompt in Gemma 4 turn format."""
        windows = window_recommendation.windows
        window_block = "\n".join(_window_line(window, index + 1) for index, window in enumerate(windows))
        if not window_block:
            window_block = "- Aday pencere hesaplanamadı."

        tags_str = ", ".join(suggested_tags) if suggested_tags else "Doğrulanmış etiket yok"

        exemplar_summaries = []
        for index, post in enumerate(similar_posts[:3], 1):
            exemplar_summaries.append(
                f"{index}. [Skor: {post.popularity_score:.1f}] {post.title[:50]} (Etiketler: {', '.join(post.tags[:3])})"
            )
        exemplars_str = "\n".join(exemplar_summaries) if exemplar_summaries else "Benzer gönderi verisi mevcut."

        media_value = media_type.value if hasattr(media_type, "value") else str(media_type)
        tz_note = (
            "Kullanıcının saat dilimi bilinmiyor; pencereler UTC'ye göre hesaplandı ve bunu açıkça belirt."
            if window_recommendation.timezone_fallback
            else f"Pencereler kullanıcının yerel saatine göre hesaplandı ({window_recommendation.timezone_label})."
        )

        prompt = (
            f"<start_of_turn>user\n"
            f"Sen NSosyal platformunun içerik ve paylaşım zamanı strateji danışmanısın (Gemma 4 Advisor).\n"
            f"Aşağıdaki içerik fikrini, kategori bilgisini, iki katmanlı modelimizin çıktısını "
            f"(içerik potansiyeli + tarihsel gözlemsel zaman pencereleri) ve Qdrant vektör aramasından "
            f"gelen en başarılı gönderileri analiz et.\n\n"
            f"İÇERİK BİLGİSİ:\n"
            f"- Fikir: {idea}\n"
            f"- Medya Türü: {media_value}\n"
            f"- Kategori: {topic}\n"
            f"- İçerik potansiyeli (zamandan bağımsız): {window_recommendation.base_potential:.2f}\n"
            f"- Güven seviyesi: {window_recommendation.confidence_label}\n\n"
            f"ÖNERİLEN ZAMAN PENCERELERİ (gözlemsel):\n"
            f"{window_block}\n\n"
            f"BENZER BAŞARILI GÖNDERİLER:\n"
            f"{exemplars_str}\n"
            f"Doğrulanmış Etiketler: {tags_str}\n\n"
            f"TALİMATLAR (ZORUNLU KURALLAR):\n"
            f"1. Kesin nedensel iddia kurma. 'Bu saatte mutlaka daha fazla etkileşim alırsın' veya "
            f"'en iyi saat kesinlikle şudur' deme.\n"
            f"2. 'Geçmiş gözlemlerde desteklenen pencere' dilini kullan ve pencereleri saat aralığı olarak ver.\n"
            f"3. Güven seviyesi düşükse bunu açıkça söyle; belirsizliği gizleme.\n"
            f"4. {tz_note}\n"
            f"5. Etiket önerisini yalnızca yukarıdaki doğrulanmış etiketlerden üret; "
            f"doğrulanmamış etiketleri güvenle önerme.\n"
            f"6. Yanıtı net, profesyonel Türkçe ile tek bir akıcı paragrafta sun.<end_of_turn>\n"
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
            f"Sen NSosyal platformunun içerik konu sınıflandırıcısısın.\n"
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
        except Exception as exc:
            logger.debug("gemma topic classification call failed: %s", exc)
            return None

        for option in options:
            if option.lower() in response_text.lower():
                return option
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
        """Calls Gemma 4 endpoint if available, falling back safely to deterministic synthesis."""
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
            endpoint = f"{self.api_url.rstrip('/')}/api/generate"
            with httpx.Client(timeout=self.timeout) as client:
                res = client.post(
                    endpoint,
                    json={"model": self.model_name, "prompt": prompt, "stream": False},
                )
                if res.status_code == 200:
                    text = (res.json().get("response") or "").strip()
                    # Accept any substantive answer instead of requiring one
                    # exact phrase; local generation often rephrases.
                    if text and len(text) >= 50:
                        return text
                    logger.debug("gemma explanation too short (%d chars); using fallback", len(text))
        except Exception as exc:
            logger.debug("gemma explanation call failed: %s; using fallback", exc)

        return fallback

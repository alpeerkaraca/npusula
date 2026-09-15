"""Centralized prompt templates for the LLM advisor, topic classification, and content moderation.

Wording is the part of this system most likely to need tuning: the advisor's
mandatory phrasing rules, the topic judge's label list and the guardrail's
safety policies are all text, not code. Keeping them here means a wording
change is a single reviewable diff instead of an edit buried in a service.

The builders are pure functions: plain arguments in, the exact string posted
to the LLM endpoint out. Nothing here talks to the network or reads settings, so a
prompt can be printed, diffed or asserted on without a model running.

The services keep their existing entry points as thin delegators
(``LLMAdvisorEngine.build_prompt``, ``LLMAdvisorEngine.classify_topic``,
``ModerationGuardrail.build_llm_prompt``) so call sites and tests are
unaffected.

Editing notes:
- Standard instruction-following chat wrappers (e.g. `<start_of_turn>user` / `<start_of_turn>model`)
  ensure models produce direct completions without continuing user prompts.
- The moderation builder's JSON block is deliberately literal braces inside an
  f-string. If you switch these to ``str.format`` you must double every brace.
- Turkish characters are intentional. These prompts are Turkish by design; the
  labels they map onto (``canonical_taxonomy``, ``CATEGORY_LABELS``) are too.
- Every rule costs generation budget. Rules are ordered by consequence, not by
  topic: what must never be dropped goes first, because a truncated answer
  loses whatever came last.
"""
from backend.schemas.post import MediaTypeEnum
from backend.schemas.recommendation import RecommendedWindow, SimilarPost, WindowRecommendation
from backend.services.time_lift import evidence_tr

__all__ = [
    "format_window_turkish",
    "build_advisor_prompt",
    "build_topic_prompt",
    "build_moderation_prompt",
    "build_vision_analysis_prompt",
    "TOPIC_DESCRIPTIONS",
    "SAFETY_POLICIES",
    "SCORE_ABOVE_MARGIN",
]


# ---------------------------------------------------------------------------
# Shared formatting
# ---------------------------------------------------------------------------

# A score this far above the population mean is called out as above average.
# The Layer A model's own MAE is ~1.9 popularity points, so a smaller gap than
# this is noise and saying "above average" about it would overstate what the
# model actually knows.
SCORE_ABOVE_MARGIN = 0.75


def format_window_turkish(window: RecommendedWindow) -> str:
    """Formats a window as ``Salı 18.00–21.00``."""
    return f"{window.weekday} {window.time_range_local}"


def _truncate(text: str, limit: int) -> str:
    """Truncates on a word boundary so an excerpt never ends mid-word."""
    if len(text) <= limit:
        return text
    cut = text[:limit].rsplit(" ", 1)[0].rstrip(".,;:")
    return f"{cut}…"


def _window_line(window: RecommendedWindow, index: int) -> str:
    support = f"{window.support_post_count} gönderi/{window.support_user_count} kullanıcı"
    lift = f"{window.observational_time_lift:+.2f}"
    return (
        f"- {index}. Pencere: {format_window_turkish(window)} "
        f"(gözlemsel lift {lift}, destek {support}, kanıt: {evidence_tr(window.evidence_level)})"
    )


def _window_block(windows: list[RecommendedWindow]) -> str:
    block = "\n".join(_window_line(window, index + 1) for index, window in enumerate(windows))
    return block or "- Aday pencere hesaplanamadı."


def _exemplar_block(similar_posts: list[SimilarPost]) -> str:
    lines = [
        f"{index}. [Skor: {post.popularity_score:.1f}] {_truncate(post.title, 50)} "
        f"(Etiketler: {', '.join(post.tags[:3])})"
        for index, post in enumerate(similar_posts[:3], 1)
    ]
    return "\n".join(lines) if lines else "Benzer gönderi verisi mevcut."


def _score_note(base_potential: float, population_mean: float | None) -> str:
    """Describes the score relative to the training population.

    A bare number is meaningless to both the model and the reader: the observed
    value 6.62 sits 0.2 above a population mean of 6.42, which is inside the
    model's own error, yet it was being reported as a precise figure. When the
    mean is unknown the note is omitted rather than guessed.
    """
    if population_mean is None:
        return ""
    delta = base_potential - population_mean
    if delta >= SCORE_ABOVE_MARGIN:
        position = "ortalamanın üstünde"
    elif delta <= -SCORE_ABOVE_MARGIN:
        position = "ortalamanın altında"
    else:
        position = "ortalamaya yakın"
    return f" (veri seti ortalaması {population_mean:.2f}; bu değer {position})"


# ---------------------------------------------------------------------------
# 1. Advisor explanation  (GemmaAdvisorEngine.generate_explanation)
# ---------------------------------------------------------------------------

def build_advisor_prompt(
    idea: str,
    topic: str,
    media_type: MediaTypeEnum,
    window_recommendation: WindowRecommendation,
    suggested_tags: list[str],
    similar_posts: list[SimilarPost],
    population_mean: float | None = None,
) -> str:
    """The explanation prompt: turn the two-layer output into Turkish prose.

    Rules 1-4 are the plan §6.2 wording rules. They exist because the model
    otherwise asserts causality about the hour, which the observational lift
    table cannot support. The deterministic fallback in
    ``GemmaAdvisorEngine._generate_fallback`` is written to the same rules, so
    the two paths read alike.

    Rules are ordered so the two disclosures that must always reach the reader
    (timezone basis, low confidence) come before stylistic ones: at a tight
    token budget the tail of the list is what gets cut.
    """
    tags_str = ", ".join(suggested_tags) if suggested_tags else "Doğrulanmış etiket yok"

    media_value = media_type.value if hasattr(media_type, "value") else str(media_type)
    tz_note = (
        "Kullanıcının saat dilimi bilinmiyor; pencereler UTC'ye göre hesaplandı ve bunu açıkça belirt."
        if window_recommendation.timezone_fallback
        else f"Pencereler kullanıcının yerel saatine göre hesaplandı ({window_recommendation.timezone_label})."
    )

    return (
        f"<start_of_turn>user\n"
        f"Sen sosyal medya platformunun içerik ve paylaşım zamanı strateji danışmanısın.\n"
        f"Aşağıdaki içerik fikrini, kategori bilgisini, iki katmanlı modelimizin çıktısını "
        f"(içerik potansiyeli + tarihsel gözlemsel zaman pencereleri) ve Qdrant vektör aramasından "
        f"gelen en başarılı gönderileri analiz et.\n\n"
        f"İÇERİK BİLGİSİ:\n"
        f"- Fikir: {idea}\n"
        f"- Medya Türü: {media_value}\n"
        f"- Kategori: {topic}\n"
        f"- İçerik potansiyeli (zamandan bağımsız, popülerlik puanı): "
        f"{window_recommendation.base_potential:.2f}{_score_note(window_recommendation.base_potential, population_mean)}\n"
        f"- Güven seviyesi: {window_recommendation.confidence_label}\n\n"
        f"ÖNERİLEN ZAMAN PENCERELERİ (gözlemsel):\n"
        f"Buradaki 'lift', pencerenin o kategorinin kendi ortalamasına göre farkıdır: "
        f"pozitif = ortalamanın üstünde, negatif = ortalamanın altında.\n"
        f"{_window_block(window_recommendation.windows)}\n\n"
        f"BENZER BAŞARILI GÖNDERİLER:\n"
        f"{_exemplar_block(similar_posts)}\n"
        f"Doğrulanmış Etiketler: {tags_str}\n\n"
        f"TALİMATLAR (ZORUNLU KURALLAR):\n"
        f"1. {tz_note}\n"
        f"2. Güven seviyesi düşükse bunu açıkça söyle; belirsizliği gizleme.\n"
        f"3. Kesin nedensel iddia kurma. 'Bu saatte mutlaka daha fazla etkileşim alırsın' veya "
        f"'en iyi saat kesinlikle şudur' deme.\n"
        f"4. 'Geçmiş gözlemlerde desteklenen pencere' dilini kullan ve pencereleri saat aralığı olarak ver.\n"
        f"5. Pencereleri sıralı sun: en yüksek lift'li olanı ilk sırada ve açıkça öne çıkar. "
        f"Negatif lift'li bir pencereyi öneri gibi gösterme; andığın gerekirse ortalamanın altında "
        f"kaldığını belirt.\n"
        f"6. İçerik potansiyeli sayısını kullanıcıya puan gibi sunma; ortalamaya göre nerede "
        f"durduğunu söyle.\n"
        f"7. Etiket önerisini yalnızca yukarıdaki doğrulanmış etiketlerden üret; "
        f"doğrulanmamış etiketleri güvenle önerme.\n"
        f"8. Selamlama, kendini tanıtma veya giriş cümlesi yazma; doğrudan öneriyle başla. "
        f"En fazla 5 cümle, tek akıcı paragraf, net ve profesyonel Türkçe.<end_of_turn>\n"
        f"<start_of_turn>model\n"
    )


# ---------------------------------------------------------------------------
# 2. Topic judge  (GemmaAdvisorEngine.classify_topic)
# ---------------------------------------------------------------------------

# Only the topics present in ``options`` are offered to the model, so this
# dict can carry more entries than any single call sends. The descriptions are
# what disambiguate the labels -- "Yaşam" vs "Spor" is not obvious from the
# bare names, which is why the model occasionally picks a neighbouring topic.
TOPIC_DESCRIPTIONS: dict[str, str] = {
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


def build_topic_prompt(idea: str, options: list[str]) -> str:
    """The topic-judge prompt. Answer is one bare label, nothing else.

    Budgeted at ``GEMMA_JUDGE_MAX_TOKENS`` (32), so the instruction to emit
    only the label is load-bearing: any preamble would push the label past the
    cap and the caller would keep its fallback.
    """
    opts = "; ".join(
        f"{name} ({desc})" for name, desc in TOPIC_DESCRIPTIONS.items() if name in options
    )
    return (
        f"<start_of_turn>user\n"
        f"Sen sosyal medya platformunun içerik konu sınıflandırıcısısın.\n"
        f"Aşağıdaki içerik fikrini YALNIZCA şu konulardan birine ata:\n{opts}\n\n"
        f"Fikir: \"{idea}\"\n\n"
        f"TALİMAT: SADECE listedeki konu adlarından birini yanıtla, başka hiçbir metin ekleme.\n"
        f"<end_of_turn>\n"
        f"<start_of_turn>model\n"
    )


# ---------------------------------------------------------------------------
# 3. Moderation arbitration  (GemmaModerationGuardrail._llm_arbitrate)
# ---------------------------------------------------------------------------

# One line per unsafe category. The leet examples ("c1pl4q", "b4h1s") are here
# on purpose: they show the model that digit substitution is a signal, not a
# typo. Note the asymmetry this creates -- only categories 1 and 2 get an
# example, and short substitutions ("51k") are deliberately left undecoded by
# AdversarialNormalizer because decoding them would corrupt real quantities
# such as "51K dolar". See _obfuscation_line for the flag that reports this.
SAFETY_POLICIES: tuple[str, ...] = (
    "1. Müstehcenlik ve Cinsellik (adult/sexual): Çıplaklık (örn. c1pl4q), pornografi, erotizm, ayak resmi/fetişi, eskort vb.",
    "2. Yasa Dışı Faaliyetler ve Kumar (illegal/gambling): Yasadışı bahis (b4h1s), kumar, uyuşturucu, silah vb.",
    "3. Şiddet ve Tehdit (violence): Fiziksel zarar, intihar veya kendine zarar verme.",
    "4. Nefret Söylemi ve Ağır Hakaret (hate_speech): Kişi veya gruplara yönelik ayrımcı, aşağılayıcı söylemler.",
    "5. KONU HAKKINDA KONUŞMAK, KONUNUN KENDİSİ DEĞİLDİR: Bir olguyu haber vermek, eleştirmek, "
    "eğitimini vermek, tedavisini anlatmak veya ona karşı farkındalık yaratmak ihlal değildir. "
    "Yalnızca içeriğin kendisi üretildiğinde, talep edildiğinde veya teşvik edildiğinde işaretle.",
)


def _obfuscation_line(leet_detected: bool) -> str:
    """Reports obfuscation state without overclaiming.

    ``leet_detected`` is False both when the normalizer looked and found
    nothing and when it declined to decode a short token. A flat "Hayır" reads
    to the model as "this text is definitely clean", which biases it toward
    ``is_safe``; measured catches rose when the flag was forced True on the
    same inputs. Saying so explicitly keeps an unchecked string from being
    treated as a cleared one.
    """
    if leet_detected:
        return "Evet"
    return "Hayır (kısa tokenlar çözülmedi; gizleme olmadığı anlamına gelmez)"


def build_moderation_prompt(text: str, normalized: str, leet_detected: bool) -> str:
    """The arbitration prompt. Must return the JSON object and nothing else.

    Budgeted at ``GEMMA_MODERATION_MAX_TOKENS`` (128); the measured verdict is
    ~68 tokens, and the headroom matters because a truncated answer fails to
    parse and ``_llm_arbitrate`` then fails open, silently dropping the stage.
    """
    policies = "\n".join(SAFETY_POLICIES)
    return (
        f"<start_of_turn>user\n"
        f"Sen sosyal medya platformunun içerik güvenliği ve moderasyon yapay zekâ danışmanısın (Content Safety Guardrail).\n"
        f"Kullanıcının ilettiği içerik fikrini platform kurallarına göre analiz et.\n\n"
        f"İÇERİK BİLGİSİ:\n"
        f"- Orijinal Metin: \"{text}\"\n"
        f"- Normalleştirilmiş Metin: \"{normalized}\"\n"
        f"- Sembol/Rakam Gizleme Tespiti: {_obfuscation_line(leet_detected)}\n\n"
        f"GÜVENLİK POLİTİKALARI:\n"
        f"{policies}\n\n"
        f"TALİMAT:\n"
        f"SADECE aşağıdaki JSON formatında yanıt ver, başka hiçbir metin ekleme:\n"
        f"{{\n"
        f"  \"is_safe\": true veya false,\n"
        f"  \"category\": \"none\" veya \"sexual_content\" veya \"gambling\" veya \"violence\" veya \"hate_speech\",\n"
        f"  \"confidence\": 0.0 - 1.0,\n"
        f"  \"reason\": \"Kullanıcıya gösterilecek nazik ve net Türkçe gerekçe\"\n"
        f"}}\n"
        f"<end_of_turn>\n"
        f"<start_of_turn>model\n"
    )


# ---------------------------------------------------------------------------
# Multimodal Vision Analysis (Multimodal VLM)
# ---------------------------------------------------------------------------
def build_vision_analysis_prompt(
    categories: list[str],
    topics: list[str],
    is_video: bool = False,
) -> str:
    """Builds the strict JSON prompt for visual media categorization and tagging."""
    cat_str = ", ".join(f'"{c}"' for c in categories)
    topic_lines = [
        f'- "{t}": {TOPIC_DESCRIPTIONS.get(t, "")}' if t in TOPIC_DESCRIPTIONS else f'- "{t}"'
        for t in topics
    ]
    top_str = "\n".join(topic_lines)
    media_desc = "video akışından örneklenmiş ardışık kareleri (2x2 ızgara)" if is_video else "yüklenen görseli"
    return (
        f"Sen sosyal medya platformunun görsel içerik analiz modelisin.\n"
        f"Sana sunulan {media_desc} dikkatle incele ve içeriği doğru şekilde sınıflandır.\n\n"
        f"İZİN VERİLEN KATEGORİLER (canonical_category):\n"
        f"[{cat_str}]\n\n"
        f"İZİN VERİLEN KONULAR (topic):\n"
        f"{top_str}\n\n"
        f"TALİMATLAR:\n"
        f"1. Görsel içeriğe en uygun tek bir 'category' seç (yalnızca izin verilen kategorilerden).\n"
        f"2. Görsel içeriğe en uygun tek bir 'topic' seç (yalnızca konu adını seç, açıklamayı değil, örn: 'Yaşam').\n"
        f"3. Görselle doğrudan ilişkili 3 adet Türkçe hashtag ('tags') üret. Her biri '#' ile başlamalıdır.\n"
        f"4. Kararın için 'category_confidence' ve 'topic_confidence' (0.0 ile 1.0 arasında birer float) belirle.\n"
        f"5. SADECE aşağıdaki JSON formatında yanıt ver, markdown veya ek metin ekleme:\n"
        f"{{\n"
        f"  \"category\": \"seçilen_kategori\",\n"
        f"  \"category_confidence\": 0.85,\n"
        f"  \"topic\": \"seçilen_konu\",\n"
        f"  \"topic_confidence\": 0.80,\n"
        f"  \"tags\": [\"#etiket1\", \"#etiket2\", \"#etiket3\"],\n"
        f"  \"description\": \"Görselin kısa Türkçe açıklaması\"\n"
        f"}}\n"
    )



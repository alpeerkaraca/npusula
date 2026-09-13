"""Model-based content safety and moderation guardrail service for NPusula.

Includes:
1. Adversarial Text Normalizer: De-obfuscates leetspeak, symbol substitutions (e.g. c1pl4q -> ciplak),
   homoglyphs, and delimiter insertions (c.i.n.s.e.l).
2. Subword & Character N-Gram Machine Learning Classifier: Calibrated multiclass model predicting
   probabilities across safety categories (safe, sexual_content, gambling, violence, hate_speech),
   delivering confidence scores and risk scores.
3. Gemma 4 / ShieldGemma Semantic Judge integration for comprehensive LLM evaluation.

Curated data (lexicon, fallback corpus, regression batteries) lives in
backend.services.moderation_data; the production classifier artifact is
trained by scripts/train_guardrail_model.py.
"""
from dataclasses import dataclass, field
import json
import logging
from pathlib import Path
import re
from typing import Any
import httpx
import joblib
import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import FeatureUnion, Pipeline

from backend.config import settings
from backend.services.moderation_data import (
    MODERATION_TRAINING_CORPUS,
    UNSAFE_LEXICON,
    strip_phrase_exceptions,
)

logger = logging.getLogger(__name__)


@dataclass
class ModerationVerdict:
    """Detailed verdict produced by the moderation model."""

    is_safe: bool
    confidence_score: float
    risk_score: float
    category: str  # "safe", "sexual_content", "gambling", "violence", "hate_speech"
    category_scores: dict[str, float] = field(default_factory=dict)
    obfuscation_detected: bool = False
    normalized_text: str = ""
    reason: str = ""
    llm_consulted: bool = False


# Leetspeak and symbol substitutions mapping to canonical Turkish/Latin characters
LEET_MAP: dict[str, str] = {
    "0": "o",
    "1": "i",
    "3": "e",
    "4": "a",
    "5": "s",
    "7": "t",
    "8": "b",
    "9": "g",
    "@": "a",
    "$": "s",
    "!": "i",
    "|": "i",
    "q": "k",
    "+": "t",
}


class AdversarialNormalizer:
    """Detects and normalizes leetspeak and delimiter evasion without
    corrupting legitimate numbers, dates, benchmarks, or technical terms."""

    # Mixed alphanumeric evasion inside a single token: letters on BOTH sides
    # of an obfuscation char (c1pl4q, n4k3d). Pure numbers (100), numeric
    # prefixes/suffixes (5G, 3D) and normal words are left untouched.
    LEET_TOKEN_RE = re.compile(r"[a-zçğıöşü]+[0134578@$!|q+][a-zçğıöşü]+")

    # Runs of at least 3 single characters separated by spaces or delimiters
    # (c i n s e l, n.a.k.e.d). Standard single-letter words do not match:
    # in "e-ticaret" or "o ve ben" the following word continues, so the run
    # of separated single characters is shorter than 3.
    SPACED_CHARS_RE = re.compile(r"(?<!\w)\w(?:[\s.\-_/]+\w(?!\w)){2}(?:[\s.\-_/]+\w(?!\w))*")

    @staticmethod
    def normalize(text: str) -> tuple[str, bool]:
        """Normalizes adversarial obfuscation in text.

        Returns (normalized_text, obfuscation_detected).
        """
        text_lower = text.lower()

        leet_detected = any(AdversarialNormalizer.LEET_TOKEN_RE.search(tok) for tok in text_lower.split())
        spacing_detected = bool(AdversarialNormalizer.SPACED_CHARS_RE.search(text_lower))

        # No obfuscation pattern: return the original text untouched
        if not (leet_detected or spacing_detected):
            return text_lower, False

        def de_leet_token(tok: str) -> str:
            if AdversarialNormalizer.LEET_TOKEN_RE.search(tok):
                return "".join(LEET_MAP.get(ch, ch) for ch in tok)
            return tok

        # 1. De-leet only tokens with mixed alphanumeric evasion patterns
        de_leet = " ".join(de_leet_token(tok) for tok in text_lower.split())

        # 2. Collapse runs of >=3 separated single characters
        if spacing_detected:
            de_leet = AdversarialNormalizer.SPACED_CHARS_RE.sub(
                lambda m: re.sub(r"[\s.\-_/]+", "", m.group(0)), de_leet
            )

        # 3. Decode obfuscation chars inside collapsed runs as well
        de_leet = " ".join(de_leet_token(tok) for tok in de_leet.split())

        cleaned = re.sub(r"\s+", " ", de_leet).strip()
        return cleaned, True


class GuardrailClassifierModel:
    """Subword & character n-gram machine learning model for content risk scoring."""

    MODEL_FILE = settings.ARTIFACTS_DIR / "guardrail_classifier.joblib"

    def __init__(self):
        self.pipeline: Pipeline | None = None
        self.classes: list[str] = []
        self._load_or_train()

    def _train(self) -> None:
        """Trains the subword & character n-gram classifier."""
        X = [item[0] for item in MODERATION_TRAINING_CORPUS]
        y = [item[1] for item in MODERATION_TRAINING_CORPUS]

        # Feature Union combines character boundary n-grams (2-5) and word n-grams (1-2)
        # Character n-grams are naturally resilient to spelling typos, leetspeak roots, and agglutination
        # max_features caps keep the fallback artifact small (same caps as the training script)
        vectorizer = FeatureUnion(
            [
                ("char", TfidfVectorizer(analyzer="char_wb", ngram_range=(2, 5), sublinear_tf=True, max_features=60_000)),
                ("word", TfidfVectorizer(analyzer="word", ngram_range=(1, 2), sublinear_tf=True, max_features=30_000)),
            ]
        )

        clf = LogisticRegression(C=1.0, max_iter=400, class_weight="balanced")
        pipe = Pipeline([("vec", vectorizer), ("clf", clf)])
        pipe.fit(X, y)

        self.pipeline = pipe
        self.classes = list(clf.classes_)

        settings.ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)
        try:
            joblib.dump(self.pipeline, self.MODEL_FILE)
        except Exception as e:
            logger.debug("failed to persist guardrail artifact to %s: %s", self.MODEL_FILE, e)

    def _load_or_train(self) -> None:
        if self.MODEL_FILE.exists():
            try:
                self.pipeline = joblib.load(self.MODEL_FILE)
                self.classes = list(self.pipeline.named_steps["clf"].classes_)
                return
            except Exception as e:
                logger.debug("failed to load guardrail artifact (%s); retraining in-process", e)
        self._train()

    def predict_scores(self, text: str) -> dict[str, float]:
        """Predicts calibrated probability distribution across all safety categories."""
        if self.pipeline is None:
            self._train()

        probs = self.pipeline.predict_proba([text])[0]
        scores: dict[str, float] = {}
        for cls_name, prob in zip(self.classes, probs):
            scores[cls_name] = round(float(prob), 4)
        return scores


class GemmaModerationGuardrail:
    """Comprehensive Guardrail combining Adversarial Normalization, ML Classifier & Gemma 4 LLM."""

    # Confidence-gated decision thresholds. Blocking requires strong model
    # confidence about a specific unsafe category; weak or split signals fail
    # open to favor legitimate content over false positives.
    # Calibrated by scripts/train_guardrail_model.py against the troff holdout
    # (see artifacts/guardrail_metrics.json).
    DECISIVE_UNSAFE_PROB = 0.85   # top unsafe category probability to block outright
    DECISIVE_RISK = 0.85          # overall risk to block outright
    OBFUSCATED_UNSAFE_PROB = 0.80  # lower bar when adversarial obfuscation is detected
    LLM_CHECK_RISK_FLOOR = 0.40    # below this risk, skip the LLM entirely

    CATEGORY_LABELS: dict[str, str] = {
        "sexual_content": "Müstehcenlik/Yetişkin İçerik",
        "gambling": "Yasa Dışı Kumar/Bahis",
        "violence": "Şiddet/Zararlı İçerik",
        "hate_speech": "Nefret Söylemi/Ayrımcılık",
    }

    REASON_TEMPLATES: dict[str, str] = {
        "sexual_content": (
            "İçerik Güvenlik İhlali (Müstehcenlik/Yetişkin İçerik): Girdiğiniz içerik fikri "
            "NSosyal Topluluk Kuralları ve Güvenlik İlkelerine aykırıdır."
        ),
        "gambling": (
            "İçerik Güvenlik İhlali (Yasa Dışı Kumar/Bahis): Yasa dışı bahis ve kumar "
            "içerikleri platform kuralları gereği optimize edilemez."
        ),
        "violence": (
            "İçerik Güvenlik İhlali (Şiddet/Zararlı İçerik): Şiddet, tehlike veya kendine "
            "zarar verme barındıran fikirler NSosyal ilkelerine aykırıdır."
        ),
        "hate_speech": (
            "İçerik Güvenlik İhlali (Nefret Söylemi): Ayrımcılık veya nefret barındıran "
            "içerikler platformumuzda desteklenmemektedir."
        ),
    }

    def __init__(
        self,
        model_name: str | None = None,
        api_url: str | None = None,
        timeout_seconds: float = 15.0,
    ):
        self.normalizer = AdversarialNormalizer()
        self.classifier = GuardrailClassifierModel()
        self.model_name = model_name or settings.GEMMA_MODEL_NAME
        self.api_url = api_url or settings.GEMMA_API_URL
        self.timeout = timeout_seconds

    def build_gemma_prompt(self, text: str, normalized: str, leet_detected: bool) -> str:
        """Constructs Gemma 4 instruction-following prompt for semantic evaluation."""
        return (
            f"<start_of_turn>user\n"
            f"Sen NSosyal platformunun içerik güvenliği ve moderasyon modelisin (Gemma Safety Guardrail / ShieldGemma).\n"
            f"Kullanıcının ilettiği içerik fikrini platform kurallarına göre analiz et.\n\n"
            f"İÇERİK BİLGİSİ:\n"
            f"- Orijinal Metin: \"{text}\"\n"
            f"- Normalleştirilmiş Metin: \"{normalized}\"\n"
            f"- Sembol/Rakam Gizleme Tespiti: {'Evet' if leet_detected else 'Hayır'}\n\n"
            f"GÜVENLİK POLİTİKALARI:\n"
            f"1. Müstehcenlik ve Cinsellik (adult/sexual): Çıplaklık (örn. c1pl4q), pornografi, erotizm, ayak resmi/fetişi, eskort vb.\n"
            f"2. Yasa Dışı Faaliyetler ve Kumar (illegal/gambling): Yasadışı bahis (b4h1s), kumar, uyuşturucu, silah vb.\n"
            f"3. Şiddet ve Tehdit (violence): Fiziksel zarar, intihar veya kendine zarar verme.\n"
            f"4. Nefret Söylemi ve Ağır Hakaret (hate_speech): Kişi veya gruplara yönelik ayrımcı, aşağılayıcı söylemler.\n\n"
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

    @staticmethod
    def _strip_phrase_exceptions(text: str) -> str:
        """Removes benign phrases (e.g. 'naked eye', 'çıplak göz') that would
        otherwise be mistaken for unsafe terms by the lexicon or the ML model."""
        return strip_phrase_exceptions(text)

    def _lexicon_check(self, normalized: str) -> str | None:
        """Scans for explicit unsafe terms with strict word boundaries (\b) in
        any language.

        Returns the unsafe category on the first hit, or None if clean.
        """
        text = self._strip_phrase_exceptions(normalized)
        for term, category in UNSAFE_LEXICON.items():
            if re.search(rf"\b{re.escape(term)}\b", text):
                return category
        return None

    def _llm_arbitrate(self, text: str, normalized: str, leet_detected: bool) -> tuple[bool, str | None, float | None, bool]:
        """Asks Gemma 4 to arbitrate uncertain ML scores.

        Returns (is_unsafe, category, confidence, llm_reached). Any failure to
        reach or parse the LLM response fails open (False, None, None, False)
        so the guardrail never blocks legitimate content on a missing model.
        llm_reached is True only when the LLM answered and its verdict was
        applied (safe or unsafe).
        """
        try:
            prompt = self.build_gemma_prompt(text, normalized, leet_detected)
            endpoint = f"{self.api_url.rstrip('/')}/api/generate"
            payload = {
                "model": self.model_name,
                "prompt": prompt,
                "stream": False,
            }
            with httpx.Client(timeout=self.timeout) as client:
                res = client.post(endpoint, json=payload)
                if res.status_code != 200:
                    # Ollama intermittently returns 500 under load; retry once
                    # before failing open (fast failure, ~0.5s extra).
                    res = client.post(endpoint, json=payload)
                if res.status_code != 200:
                    return False, None, None, False
                data = res.json()
                response_text = data.get("response", "").strip()
                json_match = re.search(r"\{.*?\}", response_text, re.DOTALL)
                if not json_match:
                    return False, None, None, False
                parsed = json.loads(json_match.group(0))
                if not isinstance(parsed, dict):
                    return False, None, None, False
                llm_is_safe = bool(parsed.get("is_safe", True))
                if not llm_is_safe:
                    llm_cat = str(parsed.get("category", "none"))
                    try:
                        llm_conf = float(parsed.get("confidence", 0.0))
                    except (TypeError, ValueError):
                        llm_conf = None
                    return True, llm_cat if llm_cat in self.CATEGORY_LABELS else None, llm_conf, True
                return False, None, None, True
        except Exception as e:
            logger.debug("llm arbitration failed (%s); failing open", e)
        return False, None, None, False

    def evaluate(self, idea: str) -> ModerationVerdict:
        """Runs multi-stage model-based safety evaluation:

        Stage 1: Adversarial Normalization (decoding leetspeak, numbers, spaced letters).
        Stage 2: Machine Learning Classification with subword & character n-grams.
        Stage 3: Confidence-gated decision; uncertain cases are arbitrated by the
                 Gemma 4 LLM if reachable, otherwise the guardrail fails open.
        """
        # Stage 1: De-obfuscate
        normalized_text, obfuscation_detected = self.normalizer.normalize(idea)

        # Stage 1.5: Deterministic multilingual lexicon check. The ML model is
        # trained on a Turkish corpus and cannot reliably recognize explicit
        # unsafe terms in other languages (e.g. "naked girls"), so explicit
        # terms are blocked deterministically regardless of ML coverage.
        lexicon_category = self._lexicon_check(normalized_text)
        if lexicon_category is not None:
            base_reason = self.REASON_TEMPLATES[lexicon_category]
            reason_msg = f"{base_reason} (Model Risk Skoru: %100, Güven: %100)."
            if obfuscation_detected:
                reason_msg += f" [Gizleme/Sembol Girişimi Tespit Edildi: '{idea}' -> '{normalized_text}']"
            scores = {cat: 0.01 for cat in ("safe", "sexual_content", "gambling", "violence", "hate_speech")}
            scores[lexicon_category] = 0.96
            return ModerationVerdict(
                is_safe=False,
                confidence_score=1.0,
                risk_score=1.0,
                category=lexicon_category,
                category_scores=scores,
                obfuscation_detected=obfuscation_detected,
                normalized_text=normalized_text,
                reason=reason_msg,
            )

        # Stage 2: Classification. Clean text is scored once on the raw input;
        # only adversarial (obfuscated) text gets the dual-view treatment with
        # the pessimistic min(safe)/max(unsafe) combine, because there the
        # normalized view is needed to decode the evasion.
        # (Benign phrases like "çıplak göz" are stripped so the ML model does
        # not flag them as unsafe terms.)
        if obfuscation_detected:
            raw_scores = self.classifier.predict_scores(self._strip_phrase_exceptions(idea))
            norm_scores = self.classifier.predict_scores(self._strip_phrase_exceptions(normalized_text))
            combined_scores: dict[str, float] = {}
            for cat in raw_scores:
                if cat == "safe":
                    combined_scores[cat] = min(raw_scores["safe"], norm_scores.get("safe", raw_scores["safe"]))
                else:
                    combined_scores[cat] = max(raw_scores.get(cat, 0.0), norm_scores.get(cat, 0.0))
        else:
            combined_scores = self.classifier.predict_scores(self._strip_phrase_exceptions(idea))

        # Overall risk is the probability mass outside "safe"
        safe_prob = combined_scores.get("safe", 0.5)
        risk_score = round(1.0 - safe_prob, 4)

        # Find the top unsafe category
        unsafe_categories = {k: v for k, v in combined_scores.items() if k != "safe"}
        top_unsafe_cat = max(unsafe_categories, key=unsafe_categories.get)
        top_unsafe_prob = unsafe_categories[top_unsafe_cat]

        # Confidence-gated decision: the ML model is only trusted to block when it is
        # confident about a *specific* unsafe category, not merely unsure about "safe".
        # Low-confidence probability splits (e.g. safe=0.41, violence=0.18) are the
        # main source of false positives and must not block.
        decisive_unsafe = top_unsafe_prob >= self.DECISIVE_UNSAFE_PROB and risk_score >= self.DECISIVE_RISK
        obfuscated_unsafe = obfuscation_detected and top_unsafe_prob >= self.OBFUSCATED_UNSAFE_PROB

        # Stage 3: LLM Cross-verification with Gemma 4 for the uncertain band.
        # The LLM arbitrates instead of the weak classifier signal; if the LLM is
        # unreachable the guardrail fails open (allows content) rather than blocking
        # legitimate content on a hunch.
        llm_unsafe = False
        llm_category = None
        llm_confidence = None
        llm_consulted = False
        if not decisive_unsafe and not obfuscated_unsafe and risk_score >= self.LLM_CHECK_RISK_FLOOR:
            llm_unsafe, llm_category, llm_confidence, llm_consulted = self._llm_arbitrate(idea, normalized_text, obfuscation_detected)
            if llm_unsafe:
                if llm_category is not None:
                    top_unsafe_cat = llm_category
                risk_score = max(risk_score, 0.90)

        # Decision: block only on decisive model confidence, obfuscated evasion, or LLM verdict
        if decisive_unsafe or obfuscated_unsafe or llm_unsafe:
            cat_label = self.CATEGORY_LABELS.get(top_unsafe_cat, "Uygunsuz İçerik")
            base_reason = self.REASON_TEMPLATES.get(
                top_unsafe_cat,
                f"İçerik Güvenlik İhlali ({cat_label}): Girdiğiniz içerik fikri topluluk kurallarına aykırıdır.",
            )

            pct_risk = int(risk_score * 100)
            reported_conf = llm_confidence if (llm_unsafe and llm_confidence is not None) else top_unsafe_prob
            pct_conf = int(reported_conf * 100)
            reason_msg = f"{base_reason} (Model Risk Skoru: %{pct_risk}, Güven: %{pct_conf})."

            if obfuscation_detected:
                reason_msg += f" [Gizleme/Sembol Girişimi Tespit Edildi: '{idea}' -> '{normalized_text}']"

            return ModerationVerdict(
                is_safe=False,
                confidence_score=round(reported_conf, 4),
                risk_score=risk_score,
                category=top_unsafe_cat,
                category_scores=combined_scores,
                obfuscation_detected=obfuscation_detected,
                normalized_text=normalized_text,
                reason=reason_msg,
                llm_consulted=llm_consulted,
            )

        return ModerationVerdict(
            is_safe=True,
            confidence_score=round(safe_prob, 4),
            risk_score=risk_score,
            category="safe",
            category_scores=combined_scores,
            obfuscation_detected=obfuscation_detected,
            normalized_text=normalized_text,
            reason="",
            llm_consulted=llm_consulted,
        )

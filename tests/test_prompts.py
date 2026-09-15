"""Prompt builders and the retry wrapper around Ollama generation.

Nothing here needs a running model: the builders are pure functions and the
retry helper is exercised through a fake HTTP client.
"""
import httpx
import pytest

from backend.schemas.post import MediaTypeEnum
from backend.services import gemma_advisor
from backend.services.gemma_advisor import GemmaAdvisorEngine
from backend.services.moderation_data import DISCUSSION_FRAMES
from backend.services.moderation import GemmaModerationGuardrail
from backend.prompts import (
    SCORE_ABOVE_MARGIN,
    build_advisor_prompt,
    build_moderation_prompt,
    _score_note,
    _truncate,
)

from tests.test_gpu_and_advisor import _recommendation, _window


def _prompt(**overrides) -> str:
    kwargs = dict(
        idea="Kahve demleme teknikleri",
        topic="Yaşam",
        media_type=MediaTypeEnum.PHOTO,
        window_recommendation=_recommendation([_window(1, 6, "Salı", 0.22)]),
        suggested_tags=["#yaşam"],
        similar_posts=[],
    )
    kwargs.update(overrides)
    return build_advisor_prompt(**kwargs)


# --------------------------------------------------------------- score band

def test_score_note_classifies_against_the_population_mean():
    mean = 6.42
    assert "ortalamanın üstünde" in _score_note(mean + SCORE_ABOVE_MARGIN + 0.1, mean)
    assert "ortalamanın altında" in _score_note(mean - SCORE_ABOVE_MARGIN - 0.1, mean)
    assert "ortalamaya yakın" in _score_note(mean + 0.1, mean)


def test_score_note_is_omitted_when_the_mean_is_unknown():
    """No baseline means no comparison -- never an invented one."""
    assert _score_note(6.62, None) == ""


def test_score_note_matches_the_observed_case():
    """6.62 against a 6.42 population mean is inside the model's error."""
    assert "ortalamaya yakın" in _score_note(6.62, 6.419046365850352)


# ------------------------------------------------------------- truncation

def test_truncate_never_cuts_mid_word():
    assert _truncate("Derin Öğrenme Mimarileri Üzerine Notlar", 20) == "Derin Öğrenme…"
    assert _truncate("kısa başlık", 50) == "kısa başlık"


def test_long_titles_are_truncated_on_a_word_boundary():
    prompt = _prompt(similar_posts=[])
    from backend.schemas.recommendation import SimilarPost

    post = SimilarPost(
        post_id="p1",
        title="Derin Öğrenme Mimarileri ve Dikkat Mekanizmaları Üzerine Uzun Bir Başlık",
        weekday=1,
        hour=21,
        popularity_score=15.0,
        similarity=0.92,
        tags=["#yapayzeka"],
    )
    prompt = _prompt(similar_posts=[post])
    excerpt = [line for line in prompt.splitlines() if "Skor:" in line][0]
    assert "…" in excerpt
    assert not excerpt.split("]")[1].strip().startswith(" ")


# ------------------------------------------------------- advisor wording

def test_advisor_prompt_explains_the_lift_scale():
    """Without this the model lists a below-average window as a recommendation."""
    prompt = _prompt()
    assert "pozitif = ortalamanın üstünde" in prompt
    assert "negatif = ortalamanın altında" in prompt


def test_advisor_prompt_forbids_greetings_and_engine_branding():
    prompt = _prompt()
    assert "Selamlama" in prompt
    assert "Gemma 4 Advisor" not in prompt


def test_advisor_prompt_orders_disclosures_before_style_rules():
    """Truncation eats the tail, so disclosures must not be last."""
    fallback_windows = _recommendation([_window(1, 6, "Salı", 0.05)], tie=True, fallback=True)
    prompt = _prompt(window_recommendation=fallback_windows)
    tz_position = prompt.index("saat dilimi bilinmiyor")
    tags_position = prompt.index("doğrulanmış etiketlerden üret")
    assert tz_position < tags_position


def test_advisor_prompt_states_the_population_mean_when_known():
    prompt = _prompt(population_mean=6.419046365850352)
    assert "veri seti ortalaması 6.42" in prompt


def test_advisor_prompt_omits_the_mean_when_unknown():
    assert "veri seti ortalaması" not in _prompt(population_mean=None)


# ----------------------------------------------------- moderation wording

def test_moderation_prompt_carries_the_discussion_rule():
    prompt = build_moderation_prompt("kumar bağımlılığı haberi", "kumar bağımlılığı haberi", False)
    assert "KONU HAKKINDA KONUŞMAK" in prompt


def test_moderation_prompt_does_not_overclaim_a_clean_obfuscation_flag():
    """False means "not decoded", which is not the same as "nothing hidden"."""
    clean = build_moderation_prompt("merhaba", "merhaba", False)
    flagged = build_moderation_prompt("n4k3d", "naked", True)
    assert "gizleme olmadığı anlamına gelmez" in clean
    assert "Gizleme Tespiti: Evet" in flagged


def test_discussion_frames_are_not_phrase_strips():
    """Frames must not delete the term: that would remove it from the review text."""
    guardrail = GemmaModerationGuardrail()
    text = "kumar bağımlılığı"
    assert guardrail._is_discussion_reference(text) is True
    assert guardrail._lexicon_check(text) == "gambling"
    assert any(frame in text for frame in DISCUSSION_FRAMES)


# -------------------------------------------- lexicon deferral (no model)

def test_lexicon_hit_without_a_discussion_frame_still_hard_blocks():
    """The deterministic path must not need the LLM."""
    guardrail = GemmaModerationGuardrail()
    guardrail.api_url = "http://127.0.0.1:9"  # nothing listens here
    guardrail.timeout = 0.1

    verdict = guardrail.evaluate("kumar oynayalim")
    assert verdict.is_safe is False
    assert verdict.category == "gambling"
    assert verdict.risk_score == 1.0


def test_deferred_lexicon_hit_blocks_when_the_llm_is_unreachable():
    """Deferral must not become a silent allow when nothing can arbitrate."""
    guardrail = GemmaModerationGuardrail()
    guardrail.api_url = "http://127.0.0.1:9"
    guardrail.timeout = 0.1

    verdict = guardrail.evaluate("Kumar bagimliligiyla ilgili bir haber paylasacagim")
    assert verdict.is_safe is False
    assert verdict.category == "gambling"


def test_undiscussed_terms_survive_inside_ordinary_text():
    guardrail = GemmaModerationGuardrail()
    assert guardrail._is_discussion_reference("porno izlemek istiyorum") is False


# --------------------------------------------------------------- retries

class _FakeResponse:
    def __init__(self, status_code: int) -> None:
        self.status_code = status_code

    def json(self) -> dict:
        # Long enough to clear generate_explanation's 50-character floor, so a
        # successful call is distinguishable from the deterministic fallback.
        return {"response": "Gözlemsel olarak desteklenen bir pencere önerisi döndü."}


class _FlakyClient:
    """Returns a scripted sequence of statuses, recording each attempt."""

    def __init__(self, statuses: list[int]) -> None:
        self.statuses = list(statuses)
        self.calls = 0

    def __enter__(self) -> "_FlakyClient":
        return self

    def __exit__(self, *exc) -> bool:
        return False

    def post(self, endpoint, json):  # noqa: A002 - mirrors httpx's keyword
        status = self.statuses[min(self.calls, len(self.statuses) - 1)]
        self.calls += 1
        return _FakeResponse(status)


@pytest.fixture
def flaky_httpx(monkeypatch):
    def install(statuses: list[int]) -> _FlakyClient:
        client = _FlakyClient(statuses)
        monkeypatch.setattr(gemma_advisor.httpx, "Client", lambda *a, **k: client)
        return client

    return install


def test_retry_recovers_from_ollama_500(flaky_httpx, monkeypatch):
    from backend.config import settings

    monkeypatch.setattr(settings, "GEMMA_RETRY_COUNT", 3)
    client = flaky_httpx([500, 200])

    res = GemmaAdvisorEngine()._post_generate("prompt", 64)
    assert res is not None and res.status_code == 200
    assert client.calls == 2


def test_retry_gives_up_after_the_configured_attempts(flaky_httpx, monkeypatch):
    from backend.config import settings

    monkeypatch.setattr(settings, "GEMMA_RETRY_COUNT", 2)
    client = flaky_httpx([500])

    assert GemmaAdvisorEngine()._post_generate("prompt", 64) is None
    assert client.calls == 2


def test_retry_uses_at_least_one_attempt(flaky_httpx, monkeypatch):
    from backend.config import settings

    monkeypatch.setattr(settings, "GEMMA_RETRY_COUNT", 0)
    client = flaky_httpx([200])

    assert GemmaAdvisorEngine()._post_generate("prompt", 64) is not None
    assert client.calls == 1


def test_generate_explanation_survives_a_transient_500(flaky_httpx, monkeypatch):
    """A single blip must not silently downgrade the answer to fallback text."""
    from backend.config import settings

    monkeypatch.setattr(settings, "GEMMA_RETRY_COUNT", 2)
    monkeypatch.setattr(settings, "GEMMA_MAX_TOKENS", 64)
    flaky_httpx([500, 200])

    engine = GemmaAdvisorEngine()
    text = engine.generate_explanation(
        idea="Kahve demleme teknikleri",
        topic="Yaşam",
        media_type=MediaTypeEnum.PHOTO,
        window_recommendation=_recommendation([_window(1, 6, "Salı", 0.22)]),
        suggested_tags=[],
        similar_posts=[],
    )
    assert text == "Gözlemsel olarak desteklenen bir pencere önerisi döndü."

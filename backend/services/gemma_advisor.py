"""Backward-compatibility module forwarding to `backend.services.llm_advisor`."""
from __future__ import annotations

import httpx  # Kept for monkeypatch fixtures in tests

from backend.services.llm_advisor import (
    GemmaAdvisorEngine,
    LLMAdvisorEngine,
    format_window_turkish,
)

__all__ = ["GemmaAdvisorEngine", "LLMAdvisorEngine", "format_window_turkish", "httpx"]

"""Loads the repository `.env` file into the process environment.

`backend/config.py`, `backend/logging_setup.py` and the scripts all go through
:func:`load_project_env`, so a value written in `.env` behaves exactly like one
exported by the shell. The precedence rule is deliberate: **the process
environment always wins**. That keeps `docker compose` (which injects its own
container-network values), CI, and one-off overrides such as
`LOG_LEVEL=DEBUG uv run uvicorn backend.app:app` working unchanged.

The file is located relative to the repository root, not the current working
directory, so scripts behave the same whether they run from the repo root or
from `scripts/`. Set `NPUSULA_ENV_FILE` to point the loader somewhere else.
"""
from __future__ import annotations

import os
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_ENV_FILE = PROJECT_ROOT / ".env"
ENV_FILE_VAR = "NPUSULA_ENV_FILE"

_QUOTES = ("'", '"')


def _parse_value(raw: str) -> str:
    """Unquoted values end at ` #`; quoted values keep everything inside."""
    value = raw.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in _QUOTES:
        return value[1:-1]
    comment = value.find(" #")
    if comment != -1:
        value = value[:comment]
    return value.rstrip()


def parse_env_file(text: str) -> dict[str, str]:
    """Parses `KEY=VALUE` lines, ignoring blank lines and `#` comments."""
    values: dict[str, str] = {}
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export "):].lstrip()
        key, separator, value = line.partition("=")
        key = key.strip()
        if not separator or not key:
            continue
        values[key] = _parse_value(value)
    return values


def load_project_env(path: Path | str | None = None, *, override: bool = False) -> dict[str, str]:
    """Reads `.env` and copies its values into `os.environ`.

    Returns the parsed values (also the ones that were skipped because the
    environment already defines them). A missing or unreadable file is not an
    error: `.env` stays optional, and every setting has a built-in default.
    """
    env_file = Path(path or os.getenv(ENV_FILE_VAR) or DEFAULT_ENV_FILE)
    try:
        text = env_file.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return {}

    values = parse_env_file(text)
    for key, value in values.items():
        # Environment entries are never overwritten: compose/CI/shell win.
        if override or key not in os.environ:
            os.environ[key] = value
    return values

"""Tests for the .env loader that feeds backend.config (backend/env_loader.py)."""
import os
import re
from pathlib import Path

import pytest

from backend.env_loader import PROJECT_ROOT, load_project_env, parse_env_file

KEY_PATTERN = re.compile(r"[A-Z_][A-Z0-9_]*")


def test_parse_env_file_handles_comments_quotes_and_export():
    parsed = parse_env_file(
        "\n".join(
            [
                "# full-line comment",
                "",
                "PLAIN=value",
                "SPACED = padded ",
                'QUOTED="two words"',
                "SINGLE='keeps # inside'",
                "export EXPORTED=from-shell",
                "WITH_COMMENT=INFO  # trailing note",
                "NO_EQUALS",
            ]
        )
    )
    assert parsed == {
        "PLAIN": "value",
        "SPACED": "padded",
        "QUOTED": "two words",
        "SINGLE": "keeps # inside",
        "EXPORTED": "from-shell",
        "WITH_COMMENT": "INFO",
    }


def test_load_project_env_fills_environment_but_never_overrides_it(tmp_path, monkeypatch):
    env_file = tmp_path / ".env"
    env_file.write_text("ENVTEST_FROM_FILE=file\nENVTEST_OVERRIDDEN=file\n", encoding="utf-8")
    monkeypatch.delenv("ENVTEST_FROM_FILE", raising=False)
    monkeypatch.setenv("ENVTEST_OVERRIDDEN", "environment")

    values = load_project_env(env_file)

    assert values == {"ENVTEST_FROM_FILE": "file", "ENVTEST_OVERRIDDEN": "file"}
    assert os.environ["ENVTEST_FROM_FILE"] == "file"
    assert os.environ["ENVTEST_OVERRIDDEN"] == "environment"


def test_load_project_env_honours_the_env_file_override(tmp_path, monkeypatch):
    env_file = tmp_path / "custom.env"
    env_file.write_text("ENVTEST_CUSTOM=yes\n", encoding="utf-8")
    monkeypatch.setenv("NPUSULA_ENV_FILE", str(env_file))
    monkeypatch.delenv("ENVTEST_CUSTOM", raising=False)

    load_project_env()

    assert os.environ["ENVTEST_CUSTOM"] == "yes"


def test_missing_env_file_is_not_an_error(tmp_path):
    assert load_project_env(tmp_path / "absent.env") == {}


def _declared_keys(path: Path) -> set[str]:
    """Keys a .env-style file defines, including the commented-out ones."""
    keys: set[str] = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip().removeprefix("#").strip()
        key, separator, _ = stripped.partition("=")
        key = key.strip()
        if separator and KEY_PATTERN.fullmatch(key):
            keys.add(key)
    return keys


def test_env_file_keeps_every_key_documented_in_the_example():
    """`.env` may add private keys, but it must not lose a documented one."""
    env_path = PROJECT_ROOT / ".env"
    if not env_path.exists():
        pytest.skip("local .env is gitignored and absent in this checkout")

    missing = _declared_keys(PROJECT_ROOT / ".env.example") - _declared_keys(env_path)
    assert not missing, f".env is missing documented keys: {sorted(missing)}"

"""Application logging configuration: plain text, level-based, no emoji.

Level is controlled by the LOG_LEVEL environment variable (default INFO).
Format: 2026-09-13 12:34:56 INFO    backend.advisor advisor completed: ...
"""
import logging
import os

LOG_FORMAT = "%(asctime)s %(levelname)-7s %(name)s %(message)s"
DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

# Third-party loggers that would otherwise be noisy at DEBUG level.
NOISY_LOGGERS = ("httpx", "httpcore", "urllib3", "qdrant_client", "lightgbm")


def setup_logging() -> None:
    """Configures the root logger once; safe to call multiple times."""
    level_name = os.getenv("LOG_LEVEL", "INFO").upper()
    level = getattr(logging, level_name, logging.INFO)

    root = logging.getLogger()
    if not any(
        isinstance(handler, logging.StreamHandler) and not isinstance(handler, logging.FileHandler)
        for handler in root.handlers
    ):
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter(LOG_FORMAT, datefmt=DATE_FORMAT))
        root.addHandler(handler)
    root.setLevel(level)

    for noisy in NOISY_LOGGERS:
        logging.getLogger(noisy).setLevel(logging.WARNING)

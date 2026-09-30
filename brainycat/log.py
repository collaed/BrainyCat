"""Structured logging — replaces silent failures with traceable events."""

from __future__ import annotations

import logging
import sys

# Configure structured logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    stream=sys.stdout,
)

logger = logging.getLogger("brainycat")


def info(msg: str, **kwargs: object) -> None:
    """Log an info-level structured event. Used throughout the codebase in place of print/silent failure."""
    logger.info(msg, extra=kwargs)


def warning(msg: str, **kwargs: object) -> None:
    """Log a warning-level structured event. Used throughout the codebase in place of print/silent failure."""
    logger.warning(msg, extra=kwargs)


def error(msg: str, **kwargs: object) -> None:
    """Log an error-level structured event. Used throughout the codebase in place of print/silent failure."""
    logger.error(msg, extra=kwargs)


async def awarning(msg: str, **kwargs: object) -> None:
    """Async wrapper around warning(), for use in async code paths (e.g. scheduler.py's background loops)."""
    logger.warning(msg, extra=kwargs)

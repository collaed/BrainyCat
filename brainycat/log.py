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
    logger.info(msg, extra=kwargs)


def warning(msg: str, **kwargs: object) -> None:
    logger.warning(msg, extra=kwargs)


def error(msg: str, **kwargs: object) -> None:
    logger.error(msg, extra=kwargs)


async def awarning(msg: str, **kwargs: object) -> None:
    logger.warning(msg, extra=kwargs)

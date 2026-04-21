"""Unit tests for logging setup."""

from brainycat.logging import log, setup_logging


def test_setup_logging_runs() -> None:
    """setup_logging configures structlog without error."""
    setup_logging()
    assert log is not None

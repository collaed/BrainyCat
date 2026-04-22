"""Tests for format conversion."""

from brainycat.format_convert import _supported_conversions


def test_weasyprint_always_available() -> None:
    paths = _supported_conversions()
    assert "epub→pdf" in paths


def test_returns_list() -> None:
    paths = _supported_conversions()
    assert isinstance(paths, list)
    assert len(paths) >= 1

"""Tests for format conversion module."""

from brainycat.format_convert import _supported_conversions, list_converters


def test_weasyprint_always_available() -> None:
    paths = _supported_conversions()
    assert "epub→pdf" in paths


def test_returns_list() -> None:
    paths = _supported_conversions()
    assert isinstance(paths, list)
    assert len(paths) >= 1


def test_list_converters_structure() -> None:
    import asyncio
    result = asyncio.get_event_loop().run_until_complete(list_converters())
    assert "weasyprint" in result
    assert "supported_conversions" in result
    assert result["weasyprint"] is True

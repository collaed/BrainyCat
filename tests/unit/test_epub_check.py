"""Tests for Calibre import and format conversion."""

from brainycat.calibre_import import detect_calibre_library
from brainycat.format_convert import _supported_conversions


def test_detect_nonexistent() -> None:
    assert detect_calibre_library("/nonexistent/path") is False


def test_detect_empty_dir() -> None:
    import tempfile
    d = tempfile.mkdtemp()
    assert detect_calibre_library(d) is False


def test_supported_conversions() -> None:
    paths = _supported_conversions()
    assert "epub→pdf" in paths

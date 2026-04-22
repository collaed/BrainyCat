"""Tests for Calibre import."""

from brainycat.calibre_import import detect_calibre_library


def test_detect_nonexistent() -> None:
    assert detect_calibre_library("/nonexistent/path") is False


def test_detect_empty_dir(tmp_path: str) -> None:
    import tempfile
    d = tempfile.mkdtemp()
    assert detect_calibre_library(d) is False

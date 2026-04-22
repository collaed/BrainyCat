"""Tests for KFX format handling."""

from brainycat.kfx import _extract_text_from_ion, is_kfx


def test_is_kfx_by_extension() -> None:
    assert is_kfx("book.kfx") is True
    assert is_kfx("book.epub") is False


def test_extract_text_from_ion() -> None:
    # Simulate Ion blob with embedded text
    blob = b"\x00\x01\x02" + b"This is a test sentence that should be extracted from the binary data" + b"\x00\x03"
    text = _extract_text_from_ion(blob)
    assert "test sentence" in text


def test_extract_text_short_runs_ignored() -> None:
    blob = b"\x00ab\x00cd\x00"
    text = _extract_text_from_ion(blob)
    assert text == ""  # Too short to extract

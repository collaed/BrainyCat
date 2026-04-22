"""Tests for KFX format handling."""

from brainycat.kfx import is_kfx


def test_is_kfx_by_extension() -> None:
    assert is_kfx("book.kfx") is True
    assert is_kfx("book.epub") is False
    assert is_kfx("book.KFX") is True


def test_is_kfx_nonexistent() -> None:
    assert is_kfx("/nonexistent/file.txt") is False


def test_extract_text_requires_ebook_convert() -> None:
    """extract_kfx_text returns empty string if ebook-convert unavailable and file doesn't exist."""
    from brainycat.kfx import extract_kfx_text
    result = extract_kfx_text("/nonexistent/file.kfx")
    assert result == ""

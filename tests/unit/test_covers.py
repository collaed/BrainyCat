"""Tests for cover generation."""
from brainycat.covers import generate_cover, _detect_genre

def test_detect_genre_erotica() -> None:
    assert _detect_genre("Femdom Story", "", "bdsm erotica") == "erotica"

def test_detect_genre_selfhelp() -> None:
    assert _detect_genre("How to Be Happy", "", "self-help guide") == "self-help"

def test_detect_genre_romance() -> None:
    assert _detect_genre("A Love Story", "", "romance passion") == "romance"

def test_detect_genre_default() -> None:
    assert _detect_genre("Random Title", "", "") == "non-fiction"

def test_generate_cover_returns_bytes() -> None:
    data = generate_cover("Test Book", "Test Author")
    assert isinstance(data, bytes)
    assert len(data) > 1000
    assert data[:2] == b"\xff\xd8"  # JPEG magic bytes

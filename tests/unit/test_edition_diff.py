"""Tests for edition diffing."""

from brainycat.edition_diff import _split_paragraphs


def test_split_paragraphs() -> None:
    text = "First paragraph here.\n\nSecond paragraph here.\n\nThird one."
    paras = _split_paragraphs(text)
    assert len(paras) == 2  # Third is too short (<20 chars)
    assert "First" in paras[0]
    assert "Second" in paras[1]


def test_split_empty() -> None:
    assert _split_paragraphs("") == []

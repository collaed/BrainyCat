"""Tests for stopwords."""

from brainycat.stopwords import STOPWORDS


def test_english_stopwords() -> None:
    assert "the" in STOPWORDS
    assert "and" in STOPWORDS
    assert "is" in STOPWORDS


def test_french_stopwords() -> None:
    assert "les" in STOPWORDS
    assert "dans" in STOPWORDS
    assert "avec" in STOPWORDS


def test_german_stopwords() -> None:
    assert "der" in STOPWORDS
    assert "und" in STOPWORDS
    assert "nicht" in STOPWORDS


def test_spanish_stopwords() -> None:
    assert "el" in STOPWORDS
    assert "pero" in STOPWORDS


def test_chinese_stopwords() -> None:
    assert "\u7684" in STOPWORDS  # 的
    assert "\u662f" in STOPWORDS  # 是


def test_luxembourgish_stopwords() -> None:
    assert "awer" in STOPWORDS
    assert "sinn" in STOPWORDS


def test_content_words_not_stopped() -> None:
    assert "python" not in STOPWORDS
    assert "book" not in STOPWORDS
    assert "library" not in STOPWORDS

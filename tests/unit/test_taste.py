"""Tests for taste engine."""

from brainycat.taste import _extract_themes, _implicit_rating, score_book, WEIGHTS


def test_weights() -> None:
    assert WEIGHTS["author"] == 2.0
    assert WEIGHTS["narrator"] == 1.5
    assert WEIGHTS["genre"] == 1.0
    assert WEIGHTS["series"] == 1.5
    assert WEIGHTS["theme"] == 0.5


def test_implicit_rating_finished() -> None:
    assert _implicit_rating(1.0, True) == 8.0
    assert _implicit_rating(0.95, True) == 8.0


def test_implicit_rating_tiers() -> None:
    assert _implicit_rating(0.85, False) == 8.0
    assert _implicit_rating(0.6, False) == 7.0
    assert _implicit_rating(0.2, False) == 6.0
    assert _implicit_rating(0.05, False) == 4.0  # Abandoned
    assert _implicit_rating(0.0, False) == 0.0


def test_extract_themes_basic() -> None:
    themes = _extract_themes("A thrilling adventure through mysterious lands")
    assert "thrilling" in themes
    assert "adventure" in themes
    assert "mysterious" in themes


def test_extract_themes_strips_html() -> None:
    themes = _extract_themes("<p>A <b>thrilling</b> adventure</p>")
    assert "thrilling" in themes


def test_extract_themes_filters_stopwords() -> None:
    themes = _extract_themes("the quick brown fox and the lazy dog")
    assert "the" not in themes
    assert "and" not in themes


def test_extract_themes_empty() -> None:
    assert _extract_themes("") == {}
    assert _extract_themes(None) == {}


def test_score_empty_profile() -> None:
    book = {"tags": ["fiction"], "authors": ["Author"], "series": []}
    profile = {"tags": {}, "authors": {}, "series": {}, "themes": {}}
    assert score_book(book, profile) == 0.0


def test_score_matching_tags() -> None:
    book = {"tags": ["romance", "drama"], "authors": [], "series": []}
    profile = {"tags": {"romance": 2.0, "drama": 1.0}, "authors": {}, "series": {}, "themes": {}}
    score = score_book(book, profile)
    assert score > 0


def test_score_author_weighted_higher() -> None:
    """Authors should score higher when profile reflects the 2.0x weight from build."""
    book_tag = {"tags": ["fiction"], "authors": [], "series": []}
    book_author = {"tags": [], "authors": ["Fav Author"], "series": []}
    # Profile values already include weights from build_taste_profile
    profile = {"tags": {"fiction": 1.0}, "authors": {"Fav Author": 2.0}, "series": {}, "themes": {}}
    assert score_book(book_author, profile) > score_book(book_tag, profile)


def test_score_rating_boost() -> None:
    book_no_rating = {"tags": ["fiction"], "authors": ["Author"], "series": []}
    book_rated = {"tags": ["fiction"], "authors": ["Author"], "series": [], "rating": 9.0}
    profile = {"tags": {"fiction": 1.0}, "authors": {"Author": 1.0}, "series": {}, "themes": {}}
    s1 = score_book(book_no_rating, profile)
    s2 = score_book(book_rated, profile)
    assert s1 > 0
    assert s2 > s1


def test_score_theme_matching() -> None:
    book = {"tags": [], "authors": [], "series": [],
            "description": "A thrilling adventure through mysterious lands"}
    profile = {"tags": {}, "authors": {}, "series": {},
               "themes": {"thrilling": 1.0, "adventure": 1.0, "mysterious": 0.5}}
    score = score_book(book, profile)
    assert score > 0

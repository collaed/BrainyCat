"""Tests for taste engine."""

from brainycat.taste import score_book


def test_score_empty_profile() -> None:
    book = {"tags": ["fiction"], "authors": ["Author"], "series": []}
    profile = {"tags": {}, "authors": {}, "series": {}}
    assert score_book(book, profile) == 0.0


def test_score_matching_tags() -> None:
    book = {"tags": ["romance", "drama"], "authors": [], "series": []}
    profile = {"tags": {"romance": 2.0, "drama": 1.0}, "authors": {}, "series": {}}
    score = score_book(book, profile)
    assert score > 0


def test_score_author_weighted_higher() -> None:
    book_tag = {"tags": ["fiction"], "authors": [], "series": []}
    book_author = {"tags": [], "authors": ["Fav Author"], "series": []}
    profile = {"tags": {"fiction": 1.0}, "authors": {"Fav Author": 1.0}, "series": {}}
    # Author weight is 2.0x, tag is 1.0x
    assert score_book(book_author, profile) > score_book(book_tag, profile)


def test_score_rating_boost() -> None:
    book_no_rating = {"tags": ["fiction"], "authors": ["Author"], "series": []}
    book_rated = {"tags": ["fiction"], "authors": ["Author"], "series": [], "rating": 9.0}
    profile = {"tags": {"fiction": 1.0}, "authors": {"Author": 1.0}, "series": {}}
    # Both have base score > 0, rated one should be higher
    s1 = score_book(book_no_rating, profile)
    s2 = score_book(book_rated, profile)
    assert s1 > 0
    assert s2 > s1

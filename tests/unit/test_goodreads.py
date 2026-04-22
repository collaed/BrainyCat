"""Tests for Goodreads CSV import."""

from brainycat.goodreads import _clean_isbn, _parse_date


def test_clean_isbn_goodreads_format() -> None:
    assert _clean_isbn('="9780123456789"') == "9780123456789"
    assert _clean_isbn('="0123456789"') == "0123456789"


def test_clean_isbn_plain() -> None:
    assert _clean_isbn("9780123456789") == "9780123456789"


def test_clean_isbn_invalid() -> None:
    assert _clean_isbn("") is None
    assert _clean_isbn("12345") is None
    assert _clean_isbn('=""') is None


def test_parse_date_formats() -> None:
    d = _parse_date("2024/03/15")
    assert d is not None
    assert d.year == 2024 and d.month == 3

    d2 = _parse_date("2024-03-15")
    assert d2 is not None

    d3 = _parse_date("03/15/2024")
    assert d3 is not None


def test_parse_date_empty() -> None:
    assert _parse_date("") is None
    assert _parse_date("not a date") is None

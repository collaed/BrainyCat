"""Tests for ISBN extraction."""
from brainycat.isbn import _clean_isbn, extract_from_text

def test_clean_isbn13() -> None:
    assert _clean_isbn("978-0-452-28143-1") == "9780452281431"
    assert _clean_isbn("9780452281431") == "9780452281431"

def test_clean_isbn10() -> None:
    assert _clean_isbn("0-452-28143-1") == "0452281431"

def test_clean_isbn_invalid() -> None:
    assert _clean_isbn("12345") is None
    assert _clean_isbn("not-an-isbn") is None

def test_extract_isbn_from_text() -> None:
    # Need enough text for front/back matter detection (>500 chars)
    text = "Copyright page\nISBN 978-0-452-28143-1\nPublished 2024\n" + "This is the body of the book. " * 200
    result = extract_from_text(text)
    assert result.get("isbn") == "9780452281431"

def test_extract_copyright_year() -> None:
    text = "© 2024 Some Publisher\n" + "x " * 500
    result = extract_from_text(text)
    assert result.get("copyright_year") == "2024"

def test_extract_publisher_en() -> None:
    text = "Published by Penguin Random House\n" + "x " * 500
    result = extract_from_text(text)
    assert "Penguin" in result.get("publisher", "")

def test_extract_number_line() -> None:
    text = "10 9 8 7 6 5 4 3 2 1\nFirst printing\n" + "x " * 500
    result = extract_from_text(text)
    assert result.get("printing_number") == 1

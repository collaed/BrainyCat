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


def test_verify_isbn13_valid() -> None:
    from brainycat.isbn import _verify_isbn13
    assert _verify_isbn13("9780452281431") is True

def test_verify_isbn13_invalid() -> None:
    from brainycat.isbn import _verify_isbn13
    assert _verify_isbn13("9780452281432") is False  # Wrong check digit

def test_verify_isbn10_valid() -> None:
    from brainycat.isbn import _verify_isbn10
    assert _verify_isbn10("0452281431") is True

def test_clean_isbn_rejects_repeating() -> None:
    assert _clean_isbn("1111111111") is None
    assert _clean_isbn("0000000000000") is None

def test_clean_isbn_valid_checksum() -> None:
    assert _clean_isbn("978-0-452-28143-1") == "9780452281431"

def test_clean_isbn_invalid_checksum() -> None:
    assert _clean_isbn("978-0-452-28143-9") is None  # Wrong check digit

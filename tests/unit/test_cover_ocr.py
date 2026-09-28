"""Tests for cover OCR ISBN extraction."""

from brainycat.cover_ocr import _find_isbn


def test_finds_isbn13_in_ocr_noise() -> None:
    text = "THE BEGINNER'S GUIDE\nSome Author\nISBN 978-0-593-47622-2\nPublisher Co"
    assert _find_isbn(text) == "9780593476222"


def test_returns_none_when_no_isbn_present() -> None:
    assert _find_isbn("Just a title and an author name, no barcode text at all") is None


def test_rejects_garbage_that_isnt_a_real_isbn() -> None:
    # A 13-digit run starting with 978 but with a bad checksum must not be "found"
    text = "978-1-111-11111-1"
    assert _find_isbn(text) is None

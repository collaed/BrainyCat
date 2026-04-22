"""Tests for incoming scanner."""
from brainycat.scanner import parse_filename

def test_parse_author_title() -> None:
    result = parse_filename("Tolkien - The Hobbit.epub")
    assert "Tolkien" in (result["author"] or "")
    assert "Hobbit" in (result["title"] or "")

def test_parse_title_only() -> None:
    result = parse_filename("The Hobbit.epub")
    assert "Hobbit" in result["title"]

def test_parse_no_extension() -> None:
    result = parse_filename("Some Book")
    assert result["title"] == "Some Book"

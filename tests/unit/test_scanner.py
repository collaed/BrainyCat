"""Tests for scanner filename parsing."""

from brainycat.scanner import parse_filename


def test_author_dash_title() -> None:
    r = parse_filename("Tolkien - The Hobbit.epub")
    assert r["author"] == "Tolkien"
    assert r["title"] == "The Hobbit"


def test_title_only() -> None:
    r = parse_filename("The Hobbit.epub")
    assert "Hobbit" in r["title"]


def test_no_extension() -> None:
    r = parse_filename("Some Book")
    assert r["title"] == "Some Book"


def test_em_dash_separator() -> None:
    r = parse_filename("Author Name \u2014 Book Title.pdf")
    assert r["author"] == "Author Name"
    assert r["title"] == "Book Title"


def test_en_dash_separator() -> None:
    r = parse_filename("Author \u2013 Title.epub")
    assert r["author"] == "Author"
    assert r["title"] == "Title"


def test_complex_filename() -> None:
    r = parse_filename("J.K. Rowling - Harry Potter and the Philosopher's Stone.epub")
    assert "Rowling" in (r["author"] or "")
    assert "Harry Potter" in r["title"]

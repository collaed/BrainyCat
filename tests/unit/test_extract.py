"""Tests for metadata extraction."""

from brainycat.extract import extract_metadata


def test_extract_unknown_format() -> None:
    result = extract_metadata("/nonexistent.xyz")
    assert result["format"] == "xyz"


def test_mobi_handler_exists() -> None:
    from brainycat.extract import _extract_mobi

    result = _extract_mobi("/nonexistent.mobi")
    assert result["format"] == "mobi"


def test_epub_isbn_rejects_non_isbn_identifiers(tmp_path) -> None:
    """A book's dc:identifier list often has a UUID/ASIN/Calibre id before the real ISBN (or no
    ISBN at all) — extraction must skip anything that doesn't checksum-validate as ISBN-10/13."""
    from ebooklib import epub

    book = epub.EpubBook()
    book.set_identifier("urn:uuid:0e59a93b-afc9-4edb-8c91-d6f4bc176b88")
    book.add_metadata("DC", "identifier", "calibre:1411")
    book.add_metadata("DC", "identifier", "urn:asin:B0D522T7R9")
    book.add_metadata("DC", "identifier", "9780593476222")  # the only real ISBN-13
    book.set_title("Test Book")
    book.set_language("en")
    chapter = epub.EpubHtml(title="Ch1", file_name="ch1.xhtml", lang="en")
    chapter.content = "<p>hi</p>"
    book.add_item(chapter)
    book.toc = (chapter,)
    book.spine = [chapter]
    book.add_item(epub.EpubNcx())
    book.add_item(epub.EpubNav())

    path = str(tmp_path / "book.epub")
    epub.write_epub(path, book)

    result = extract_metadata(path)
    assert result["isbn"] == "9780593476222"


def test_epub_isbn_none_when_no_identifier_validates(tmp_path) -> None:
    from ebooklib import epub

    book = epub.EpubBook()
    book.set_identifier("urn:uuid:8850bc1c-6818-4734-b9f5-5d04ad413d0d")
    book.set_title("Test Book 2")
    book.set_language("en")
    chapter = epub.EpubHtml(title="Ch1", file_name="ch1.xhtml", lang="en")
    chapter.content = "<p>hi</p>"
    book.add_item(chapter)
    book.toc = (chapter,)
    book.spine = [chapter]
    book.add_item(epub.EpubNcx())
    book.add_item(epub.EpubNav())

    path = str(tmp_path / "book2.epub")
    epub.write_epub(path, book)

    result = extract_metadata(path)
    assert result["isbn"] is None

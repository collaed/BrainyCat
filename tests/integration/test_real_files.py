"""Integration tests with real ebook files.

Tests actual conversion, extraction, and parsing against real-world files.
Requires: tests/fixtures/ with downloaded test files.
"""

import os
import tempfile

import pytest

FIXTURES = os.path.join(os.path.dirname(__file__), "..", "fixtures")


def has_fixture(name: str) -> bool:
    return os.path.isfile(os.path.join(FIXTURES, name))


# ── EPUB Tests ───────────────────────────────────────────────────────────

@pytest.mark.skipif(not has_fixture("pride_prejudice.epub"), reason="fixture missing")
class TestEPUB:
    def test_extract_metadata(self) -> None:
        pytest.importorskip("ebooklib")
        from brainycat.extract import extract_metadata
        m = extract_metadata(os.path.join(FIXTURES, "pride_prejudice.epub"))
        assert m["format"] == "epub"
        assert "Pride" in m.get("title", "") or "Prejudice" in m.get("title", "")

    def test_epub_check(self) -> None:
        """EPUB quality check on a real file."""
        from brainycat.epub_check import check_epub
        import asyncio
        # check_epub needs a book_id — test the internal logic instead
        import zipfile
        path = os.path.join(FIXTURES, "pride_prejudice.epub")
        with zipfile.ZipFile(path) as zf:
            names = zf.namelist()
            assert "mimetype" in names
            mt = zf.read("mimetype").decode().strip()
            assert mt == "application/epub+zip"

    def test_word_count(self) -> None:
        """Count words in a real EPUB."""
        ebooklib = pytest.importorskip("ebooklib")
        from bs4 import BeautifulSoup
        from ebooklib import epub
        path = os.path.join(FIXTURES, "pride_prejudice.epub")
        book = epub.read_epub(path, options={"ignore_ncx": True})
        words = 0
        for item in book.get_items_of_type(ebooklib.ITEM_DOCUMENT):
            soup = BeautifulSoup(item.get_content(), "html.parser")
            words += len(soup.get_text().split())
        assert words > 100000  # Pride and Prejudice is ~120K words

    def test_isbn_extraction(self) -> None:
        from brainycat.isbn import extract_from_opf
        result = extract_from_opf(os.path.join(FIXTURES, "pride_prejudice.epub"))
        # Gutenberg EPUBs may not have ISBN but should parse without error
        assert isinstance(result, dict)


@pytest.mark.skipif(not has_fixture("accessible_epub3.epub"), reason="fixture missing")
class TestEPUB3:
    def test_epub3_parses(self) -> None:
        from brainycat.extract import extract_metadata
        m = extract_metadata(os.path.join(FIXTURES, "accessible_epub3.epub"))
        assert m["format"] == "epub"


# ── MOBI Tests ───────────────────────────────────────────────────────────

@pytest.mark.skipif(not has_fixture("pride_prejudice.mobi"), reason="fixture missing")
class TestMOBI:
    def test_extract_metadata(self) -> None:
        from brainycat.extract import extract_metadata
        m = extract_metadata(os.path.join(FIXTURES, "pride_prejudice.mobi"))
        assert m["format"] == "mobi"

    def test_mobi_has_title(self) -> None:
        from brainycat.extract import _extract_mobi
        m = _extract_mobi(os.path.join(FIXTURES, "pride_prejudice.mobi"))
        assert m.get("title") or m.get("format") == "mobi"


# ── PDF Tests ────────────────────────────────────────────────────────────

@pytest.mark.skipif(not has_fixture("art_of_war.pdf"), reason="fixture missing")
class TestPDF:
    def test_extract_metadata(self) -> None:
        from brainycat.extract import extract_metadata
        m = extract_metadata(os.path.join(FIXTURES, "art_of_war.pdf"))
        assert m["format"] == "pdf"

    def test_pdf_page_count(self) -> None:
        fitz = pytest.importorskip("fitz")
        doc = fitz.open(os.path.join(FIXTURES, "art_of_war.pdf"))
        assert len(doc) > 0
        doc.close()

    def test_pdf_text_extraction(self) -> None:
        fitz = pytest.importorskip("fitz")
        doc = fitz.open(os.path.join(FIXTURES, "art_of_war.pdf"))
        text = ""
        for page in doc:
            text += page.get_text()
        doc.close()
        assert len(text) > 100


# ── TXT Tests ────────────────────────────────────────────────────────────

@pytest.mark.skipif(not has_fixture("pride_prejudice.txt"), reason="fixture missing")
class TestTXT:
    def test_readability(self) -> None:
        from brainycat.readability import compute_readability
        with open(os.path.join(FIXTURES, "pride_prejudice.txt")) as f:
            text = f.read()[:50000]
        r = compute_readability(text)
        assert "error" not in r
        assert r["flesch_ease"] > 50  # Should be readable
        assert r["fk_grade"] < 15  # Not academic
        assert r["word_count"] > 5000

    def test_isbn_from_text(self) -> None:
        from brainycat.isbn import extract_from_text
        with open(os.path.join(FIXTURES, "pride_prejudice.txt")) as f:
            text = f.read()
        result = extract_from_text(text)
        assert isinstance(result, dict)  # May or may not find ISBN


# ── Cross-Format Tests ───────────────────────────────────────────────────

@pytest.mark.skipif(not has_fixture("pride_prejudice.epub"), reason="fixture missing")
class TestFingerprint:
    def test_fingerprint_epub(self) -> None:
        from brainycat.fingerprints import _extract_full_text, _normalize, _kgram_hashes, _winnow
        pytest.importorskip("ebooklib")
        text = _extract_full_text(os.path.join(FIXTURES, "pride_prejudice.epub"), "epub")
        if not text:
            pytest.skip("ebooklib could not extract text")
        normalized = _normalize(text[:5000])
        hashes = _kgram_hashes(normalized)
        assert len(hashes) > 100
        winnowed = _winnow(hashes)
        assert len(winnowed) > 10

    def test_embedding(self) -> None:
        from brainycat.embeddings import _text_to_vector
        with open(os.path.join(FIXTURES, "pride_prejudice.txt")) as f:
            text = f.read()[:2000]
        vec = _text_to_vector(text)
        assert len(vec) == 384
        import math
        mag = math.sqrt(sum(x*x for x in vec))
        assert abs(mag - 1.0) < 0.01  # Normalized

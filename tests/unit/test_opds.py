"""Tests for OPDS feed."""

from brainycat.opds import _entry, _esc


def test_entry_acquisition_link_hits_the_real_download_route() -> None:
    """The acquisition link must point at /file/by-format/{fmt} — the actual registered route.
    A book_id/{fmt} link (no 'by-format' segment) looks similar but 500s: serve_file() tries to
    parse {fmt} ('epub'/'pdf') as a file UUID."""
    book = {
        "id": "11111111-1111-1111-1111-111111111111",
        "title": "T",
        "description": "",
        "isbn": None,
        "authors": [],
        "formats": ["epub", "pdf"],
        "updated_at": None,
        "page_count": None,
        "estimated_reading_minutes": None,
        "quality_score": None,
    }
    xml = _entry(book)
    assert "/file/by-format/epub" in xml
    assert "/file/by-format/pdf" in xml
    assert '/file/epub"' not in xml
    assert '/file/pdf"' not in xml


def test_esc_ampersand() -> None:
    assert _esc("A & B") == "A &amp; B"


def test_esc_angle_brackets() -> None:
    assert _esc("<tag>") == "&lt;tag&gt;"


def test_esc_clean() -> None:
    assert _esc("normal text") == "normal text"


def test_esc_empty() -> None:
    assert _esc("") == ""

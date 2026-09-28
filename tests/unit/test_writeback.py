"""Tests for metadata writeback into book files."""

import shutil

import fitz
import pytest

from brainycat.writeback import _update_pdf_info

FIXTURE = "tests/fixtures/art_of_war.pdf"


def test_update_pdf_info_writes_title_and_author(tmp_path) -> None:
    path = str(tmp_path / "book.pdf")
    shutil.copy2(FIXTURE, path)

    _update_pdf_info(path, title="A Corrected Title", authors=["Author One", "Author Two"])

    doc = fitz.open(path)
    meta = doc.metadata
    doc.close()
    assert meta["title"] == "A Corrected Title"
    assert meta["author"] == "Author One, Author Two"


def test_update_pdf_info_noop_fields_leave_existing_metadata(tmp_path) -> None:
    path = str(tmp_path / "book.pdf")
    shutil.copy2(FIXTURE, path)
    doc = fitz.open(path)
    original_title = doc.metadata.get("title")
    doc.close()

    _update_pdf_info(path, title=None, authors=None)

    doc = fitz.open(path)
    meta = doc.metadata
    doc.close()
    assert meta.get("title") == original_title

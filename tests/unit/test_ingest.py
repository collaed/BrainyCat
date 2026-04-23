"""Tests for ingest pipeline and delivery format selection."""

from brainycat.ingest import choose_delivery_format


def test_kindle_scribe_gets_pdf() -> None:
    assert choose_delivery_format("Kindle Scribe", ["epub", "pdf"]) == "pdf"


def test_kindle_scribe_even_without_pdf() -> None:
    assert choose_delivery_format("Kindle Scribe", ["epub"]) == "pdf"


def test_regular_kindle_prefers_azw3() -> None:
    assert choose_delivery_format("Kindle", ["epub", "azw3", "pdf"]) == "azw3"


def test_regular_kindle_falls_back_to_mobi() -> None:
    assert choose_delivery_format("Kindle", ["epub", "mobi"]) == "mobi"


def test_kobo_prefers_kepub() -> None:
    assert choose_delivery_format("Kobo", ["epub", "kepub"]) == "kepub"


def test_generic_prefers_epub() -> None:
    assert choose_delivery_format("generic", ["epub", "pdf"]) == "epub"


def test_workbook_always_pdf() -> None:
    assert choose_delivery_format("Kindle", ["epub", "azw3"], is_workbook=True) == "pdf"
    assert choose_delivery_format("Kobo", ["epub", "kepub"], is_workbook=True) == "pdf"
    assert choose_delivery_format("Kindle Scribe", ["epub"], is_workbook=True) == "pdf"

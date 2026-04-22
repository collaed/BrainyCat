"""Tests for Kobo KEPUB conversion."""

from brainycat.kepub import _add_kobo_spans


def test_add_kobo_spans_wraps_paragraphs() -> None:
    html = "<p>Hello world</p><p>Second paragraph</p>"
    result = _add_kobo_spans(html)
    assert 'class="koboSpan"' in result
    assert "kobo.1.1" in result
    assert "kobo.2.1" in result


def test_add_kobo_spans_preserves_non_p() -> None:
    html = "<h1>Title</h1><p>Content</p>"
    result = _add_kobo_spans(html)
    assert "<h1>Title</h1>" in result
    assert "koboSpan" in result


def test_add_kobo_spans_empty() -> None:
    assert _add_kobo_spans("") == ""

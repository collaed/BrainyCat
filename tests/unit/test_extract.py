"""Tests for metadata extraction."""
from brainycat.extract import extract_metadata

def test_extract_unknown_format() -> None:
    result = extract_metadata("/nonexistent.xyz")
    assert result["format"] == "xyz"

def test_mobi_handler_exists() -> None:
    from brainycat.extract import _extract_mobi
    result = _extract_mobi("/nonexistent.mobi")
    assert result["format"] == "mobi"

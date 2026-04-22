"""Tests for DeACSM module."""

from brainycat.deacsm import is_acsm


def test_is_acsm_by_extension() -> None:
    assert is_acsm("book.acsm") is True
    assert is_acsm("book.epub") is False


def test_is_acsm_nonexistent_file() -> None:
    assert is_acsm("/nonexistent/file.txt") is False

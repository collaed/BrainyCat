"""Tests for storage module."""

from brainycat.storage import book_dir


def test_book_dir() -> None:
    result = book_dir("test-id-123")
    assert "test-id-123" in result
    assert isinstance(result, str)

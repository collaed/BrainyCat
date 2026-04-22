"""Tests for storage module."""

from brainycat.storage import book_dir, delete_book_dir


def test_book_dir_contains_id() -> None:
    result = book_dir("abc-123")
    assert "abc-123" in result


def test_book_dir_returns_string() -> None:
    assert isinstance(book_dir("test"), str)


def test_delete_nonexistent_dir() -> None:
    """Deleting a nonexistent dir should not raise."""
    delete_book_dir("nonexistent-id-12345")  # Should not raise

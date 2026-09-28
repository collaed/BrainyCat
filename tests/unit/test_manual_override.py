"""Tests for manual identity override."""

from unittest.mock import AsyncMock, patch

import pytest

from brainycat.manual_override import apply_override


BOOK_ID = "11111111-1111-1111-1111-111111111111"


@pytest.mark.asyncio
async def test_apply_override_rejects_invalid_isbn() -> None:
    with patch("brainycat.manual_override.fetch_one", new_callable=AsyncMock) as mock_fetch:
        mock_fetch.return_value = {"title": "Old Title", "isbn": None, "description": None}
        result = await apply_override(BOOK_ID, title="New Title", isbn="not-a-real-isbn")
    assert "error" in result
    assert "checksum" in result["error"]


@pytest.mark.asyncio
async def test_apply_override_missing_book() -> None:
    with patch("brainycat.manual_override.fetch_one", new_callable=AsyncMock) as mock_fetch:
        mock_fetch.return_value = None
        result = await apply_override(BOOK_ID, title="New Title")
    assert result == {"error": "not found"}

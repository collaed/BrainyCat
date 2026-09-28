"""Tests for the Gutendex source — must fail fast and gracefully.

Regression: search()/browse()/get_book() had no per-call timeout and no error handling, so an
unreachable/slow gutendex.com silently ate the caller's whole enrichment time budget (~15-30s per
book) instead of returning None. See sources/gutendex.py.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import httpx
import pytest

from brainycat.sources import gutendex


@pytest.mark.asyncio
async def test_search_returns_none_on_timeout() -> None:
    with patch("brainycat.sources.gutendex.get_client") as mock_client:
        mock_client.return_value.get = AsyncMock(side_effect=httpx.TimeoutException("boom"))
        assert await gutendex.search(title="anything") is None


@pytest.mark.asyncio
async def test_get_book_returns_none_on_timeout() -> None:
    with patch("brainycat.sources.gutendex.get_client") as mock_client:
        mock_client.return_value.get = AsyncMock(side_effect=httpx.TimeoutException("boom"))
        assert await gutendex.get_book(1) is None


@pytest.mark.asyncio
async def test_browse_returns_empty_on_timeout() -> None:
    with patch("brainycat.sources.gutendex.get_client") as mock_client:
        mock_client.return_value.get = AsyncMock(side_effect=httpx.TimeoutException("boom"))
        result = await gutendex.browse()
        assert result == {"count": 0, "books": []}


@pytest.mark.asyncio
async def test_search_passes_a_short_timeout() -> None:
    """The per-call timeout must stay well under the caller's 15s-per-source budget (metadata.py)."""
    with patch("brainycat.sources.gutendex.get_client") as mock_client:
        get = AsyncMock(return_value=httpx.Response(200, json={"count": 0, "results": []}))
        mock_client.return_value.get = get
        await gutendex.search(title="anything")
        assert get.call_args.kwargs["timeout"] <= 10

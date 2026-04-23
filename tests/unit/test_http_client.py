"""Tests for shared HTTP client."""

import pytest
from brainycat.http_client import get_client, close_client


def test_get_client_returns_client() -> None:
    client = get_client()
    assert client is not None
    assert not client.is_closed


def test_get_client_reuses() -> None:
    c1 = get_client()
    c2 = get_client()
    assert c1 is c2


@pytest.mark.asyncio
async def test_close_client() -> None:
    get_client()
    await close_client()
    # Next call should create a new one
    c = get_client()
    assert not c.is_closed
    await close_client()

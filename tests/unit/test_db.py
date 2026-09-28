"""Unit tests for database module."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from brainycat import db


@pytest.mark.asyncio
async def test_get_pool_creates_pool() -> None:
    """get_pool creates a connection pool on first call."""
    db._pool = None
    mock_pool = AsyncMock()
    with patch("asyncpg.create_pool", new_callable=AsyncMock, return_value=mock_pool):
        pool = await db.get_pool()
    assert pool is mock_pool
    db._pool = None  # cleanup


@pytest.mark.asyncio
async def test_get_pool_reuses_pool() -> None:
    """get_pool returns existing pool on subsequent calls."""
    mock_pool = AsyncMock()
    db._pool = mock_pool
    pool = await db.get_pool()
    assert pool is mock_pool
    db._pool = None


@pytest.mark.asyncio
async def test_close_pool() -> None:
    """close_pool closes and clears the pool."""
    mock_pool = AsyncMock()
    db._pool = mock_pool
    await db.close_pool()
    mock_pool.close.assert_awaited_once()
    assert db._pool is None


@pytest.mark.asyncio
async def test_close_pool_noop_when_none() -> None:
    """close_pool does nothing when pool is None."""
    db._pool = None
    await db.close_pool()
    assert db._pool is None


@pytest.mark.asyncio
async def test_fetch_one() -> None:
    """fetch_one delegates to pool.fetchrow."""
    mock_pool = AsyncMock()
    mock_pool.fetchrow = AsyncMock(return_value={"id": 1})
    db._pool = mock_pool
    result = await db.fetch_one("SELECT 1")
    mock_pool.fetchrow.assert_awaited_once_with("SELECT 1")
    assert result == {"id": 1}
    db._pool = None


@pytest.mark.asyncio
async def test_fetch_all() -> None:
    """fetch_all delegates to pool.fetch."""
    mock_pool = AsyncMock()
    mock_pool.fetch = AsyncMock(return_value=[{"id": 1}])
    db._pool = mock_pool
    result = await db.fetch_all("SELECT 1")
    assert result == [{"id": 1}]
    db._pool = None


@pytest.mark.asyncio
async def test_execute() -> None:
    """execute delegates to pool.execute."""
    mock_pool = AsyncMock()
    mock_pool.execute = AsyncMock(return_value="INSERT 0 1")
    db._pool = mock_pool
    result = await db.execute("INSERT INTO t VALUES (1)")
    assert result == "INSERT 0 1"
    db._pool = None


@pytest.mark.asyncio
async def test_health_check_success() -> None:
    """health_check returns connected status."""
    mock_pool = AsyncMock()
    mock_row = MagicMock()
    mock_row.__getitem__ = lambda self, key: 1 if key == "ok" else None
    mock_pool.fetchrow = AsyncMock(return_value=mock_row)
    mock_pool.fetchval = AsyncMock(side_effect=["16.13", True, True])
    db._pool = mock_pool
    result = await db.health_check()
    assert result["connected"] is True
    assert result["version"] == "16.13"
    db._pool = None


@pytest.mark.asyncio
async def test_health_check_failure() -> None:
    """health_check returns error on connection failure."""
    db._pool = None
    with patch("asyncpg.create_pool", new_callable=AsyncMock, side_effect=ConnectionRefusedError("refused")):
        result = await db.health_check()
    assert result["connected"] is False
    assert "refused" in result["error"]
    db._pool = None


def test_encode_json_passes_through_already_serialized_strings() -> None:
    """Regression: 42+ call sites across the codebase already do json.dumps(...) themselves before
    binding a jsonb parameter (the only workaround available before the codec existed). The encoder
    must not re-encode that, or every one of those writes double-encodes (a JSON string containing
    escaped JSON text, instead of the intended object) — found live via settings/languages roundtripping
    to '["en", "de"]' (a string) instead of ["en", "de"] (a list) before this fix."""
    import json

    already_serialized = json.dumps(["en", "de"])
    assert db._encode_json(already_serialized) == already_serialized


def test_encode_json_encodes_raw_python_values() -> None:
    """New code that binds a raw dict/list directly (not pre-serialized) still gets encoded."""
    import json

    assert db._encode_json({"a": 1}) == json.dumps({"a": 1})
    assert db._encode_json(["en", "de"]) == json.dumps(["en", "de"])

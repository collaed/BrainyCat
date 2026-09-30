"""Database connection pool and helpers."""

from __future__ import annotations

import contextlib
import json
from collections.abc import AsyncIterator
from typing import Any

import asyncpg

from brainycat.config import settings
from brainycat.logging import log

_pool: asyncpg.Pool | None = None  # type: ignore[type-arg]


def _encode_json(value: Any) -> str:
    """Encode a value for a jsonb parameter, passing already-serialized strings through unchanged. Internal codec used by the connection pool for jsonb binds."""
    # 42+ call sites across 30 files already do `json.dumps(...)` themselves before binding a jsonb
    # parameter (the established, only-option workaround for this codec never having existed). An
    # unconditional encoder here would double-encode every one of them. Passing an already-serialized
    # string through unchanged preserves all of that existing behavior exactly, while still letting any
    # *new* code bind a raw dict/list directly.
    return value if isinstance(value, str) else json.dumps(value)


async def _init_connection(conn: asyncpg.Connection) -> None:  # type: ignore[type-arg]
    """Without this, asyncpg returns json/jsonb columns as raw strings, not dicts/lists — every
    column read (users.preferences, books.extra_metadata, etc.) silently needed a manual json.loads(),
    and most call sites didn't do it. Found via users.preferences after adding it in migration 008:
    routes/auth.py's language-prefs read crashed outright (`'str' object has no attribute 'get'`), while
    social.py's public-feed read had an isinstance(..., dict) guard that silently treated the string as
    empty instead of crashing — same root cause, two different symptoms."""
    await conn.set_type_codec("json", encoder=_encode_json, decoder=json.loads, schema="pg_catalog")
    await conn.set_type_codec("jsonb", encoder=_encode_json, decoder=json.loads, schema="pg_catalog")


async def get_pool() -> asyncpg.Pool:  # type: ignore[type-arg]
    """Return the global connection pool, creating it on first call."""
    global _pool
    if _pool is None:
        _pool = await asyncpg.create_pool(
            settings.database_url,
            min_size=3,
            max_size=20,
            command_timeout=60,
            server_settings={"statement_timeout": "30000"},  # 30s max query
            init=_init_connection,
        )
        await log.ainfo("db_pool_created")
    return _pool


async def close_pool() -> None:
    """Close the connection pool."""
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None
        await log.ainfo("db_pool_closed")


async def fetch_one(query: str, *args: Any) -> asyncpg.Record | None:
    """Execute a query and return a single row."""
    pool = await get_pool()
    return await pool.fetchrow(query, *args)


async def fetch_all(query: str, *args: Any) -> list[asyncpg.Record]:
    """Execute a query and return all rows."""
    pool = await get_pool()
    return await pool.fetch(query, *args)


async def execute(query: str, *args: Any) -> str:
    """Execute a query and return the status."""
    pool = await get_pool()
    return await pool.execute(query, *args)


@contextlib.asynccontextmanager
async def transaction() -> AsyncIterator[asyncpg.Connection]:  # type: ignore[type-arg]
    """A connection with an open transaction, for a multi-statement write that must not leave
    partial state on a crash mid-sequence (e.g. delete-then-reinsert author links)."""
    pool = await get_pool()
    async with pool.acquire() as conn, conn.transaction():
        yield conn


async def health_check() -> dict[str, Any]:
    """Check database connectivity and extensions."""
    try:
        pool = await get_pool()
        row = await pool.fetchrow("SELECT 1 AS ok")
        pg_version = await pool.fetchval("SHOW server_version")

        # Check pgvector
        pgvector = await pool.fetchval("SELECT EXISTS(SELECT 1 FROM pg_extension WHERE extname = 'vector')")
        # Check pg_trgm
        pg_trgm = await pool.fetchval("SELECT EXISTS(SELECT 1 FROM pg_extension WHERE extname = 'pg_trgm')")

        return {
            "connected": row is not None and row["ok"] == 1,
            "version": pg_version,
            "pgvector": pgvector,
            "pg_trgm": pg_trgm,
        }
    except Exception as e:
        return {"connected": False, "error": str(e)}

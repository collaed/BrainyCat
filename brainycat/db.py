"""Database connection pool and helpers."""

from __future__ import annotations

from typing import Any

import asyncpg

from brainycat.config import settings
from brainycat.logging import log

_pool: asyncpg.Pool | None = None  # type: ignore[type-arg]


async def get_pool() -> asyncpg.Pool:  # type: ignore[type-arg]
    """Return the global connection pool, creating it on first call."""
    global _pool
    if _pool is None:
        _pool = await asyncpg.create_pool(settings.database_url, min_size=2, max_size=10)
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

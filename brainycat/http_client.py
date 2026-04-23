"""Shared HTTP client — connection pooling for all external API calls.

Replaces 66 separate httpx.AsyncClient instantiations with one shared pool.
"""

from __future__ import annotations

import httpx

_client: httpx.AsyncClient | None = None


def get_client() -> httpx.AsyncClient:
    """Get or create the shared HTTP client with connection pooling."""
    global _client
    if _client is None or _client.is_closed:
        _client = httpx.AsyncClient(
            timeout=30,
            follow_redirects=True,
            limits=httpx.Limits(max_connections=20, max_keepalive_connections=10),
        )
    return _client


async def close_client() -> None:
    """Close the shared client on shutdown."""
    global _client
    if _client and not _client.is_closed:
        await _client.aclose()
        _client = None

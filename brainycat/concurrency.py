"""Request concurrency control — limit heavy operations, let light ones through."""

from __future__ import annotations

import asyncio
from functools import wraps
from typing import Any

# Heavy ops: enrichment, OCR, conversion, TTS, batch operations
# These hit external APIs, do CPU work, or hold DB connections long
_heavy_sem = asyncio.Semaphore(2)

# Light ops: reads, searches, cover serving — unlimited (async handles thousands)


def heavy(fn: Any) -> Any:
    """Decorator: limit to 2 concurrent heavy operations."""

    @wraps(fn)
    async def wrapper(*args: Any, **kwargs: Any) -> Any:
        async with _heavy_sem:
            return await fn(*args, **kwargs)

    return wrapper

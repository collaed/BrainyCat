"""Retry wrapper for external API calls — resilience against transient failures."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any, TypeVar

if TYPE_CHECKING:
    from collections.abc import Callable

T = TypeVar("T")


async def with_retry(
    fn: Callable[..., Any],
    *args: Any,
    retries: int = 2,
    delay: float = 1.0,
    **kwargs: Any,
) -> Any:
    """Call fn with retry on failure. Returns None on all failures."""
    for attempt in range(retries + 1):
        try:
            result = await fn(*args, **kwargs)
            if result is not None:
                return result
        except Exception:
            if attempt < retries:
                await asyncio.sleep(delay * (attempt + 1))
    return None

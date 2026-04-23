"""Rate limiter — prevents IP bans from external APIs.

Simple token bucket per domain. Configurable rates.
"""

from __future__ import annotations

import asyncio
import time


class RateLimiter:
    """Token bucket rate limiter per domain."""

    def __init__(self) -> None:
        self._buckets: dict[str, float] = {}  # domain → last_request_time
        self._rates: dict[str, float] = {
            "google": 2.0,  # 2 seconds between Google requests
            "amazon": 3.0,
            "openlibrary": 1.0,
            "librivox": 1.0,
            "gutendex": 1.0,
            "apple": 1.0,
            "default": 1.0,
        }

    async def wait(self, domain: str) -> None:
        """Wait if needed to respect rate limit for this domain."""
        key = "default"
        for k in self._rates:
            if k in domain:
                key = k
                break

        now = time.monotonic()
        last = self._buckets.get(key, 0)
        wait_time = self._rates[key] - (now - last)

        if wait_time > 0:
            await asyncio.sleep(wait_time)

        self._buckets[key] = time.monotonic()


# Global instance
rate_limiter = RateLimiter()

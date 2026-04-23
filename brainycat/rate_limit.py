"""Adaptive rate limiter — backs off when sources start failing.

Simple token bucket per domain + failure tracking.
After N consecutive failures, exponentially increases delay.
Resets on success.
"""

from __future__ import annotations

import asyncio
import time


class RateLimiter:
    def __init__(self) -> None:
        self._last_request: dict[str, float] = {}
        self._base_rates: dict[str, float] = {
            "google": 2.0,
            "amazon": 5.0,
            "openlibrary": 1.5,
            "librivox": 1.0,
            "gutendex": 1.5,
            "apple": 1.0,
            "loc": 2.0,
            "default": 1.0,
        }
        self._consecutive_failures: dict[str, int] = {}
        self._backoff_until: dict[str, float] = {}

    def _key(self, domain: str) -> str:
        for k in self._base_rates:
            if k in domain:
                return k
        return "default"

    async def wait(self, domain: str) -> None:
        """Wait if needed. Respects both rate limit and failure backoff."""
        key = self._key(domain)

        # Check if we're in backoff
        backoff_until = self._backoff_until.get(key, 0)
        now = time.monotonic()
        if now < backoff_until:
            wait = backoff_until - now
            if wait > 300:  # Cap at 5 minutes
                self._backoff_until[key] = now + 300
                wait = 300
            await asyncio.sleep(wait)
            return

        # Normal rate limiting
        last = self._last_request.get(key, 0)
        rate = self._base_rates.get(key, 1.0)
        wait_time = rate - (now - last)
        if wait_time > 0:
            await asyncio.sleep(wait_time)

        self._last_request[key] = time.monotonic()

    def report_success(self, domain: str) -> None:
        """Reset failure counter on success."""
        key = self._key(domain)
        self._consecutive_failures[key] = 0
        self._backoff_until[key] = 0

    def report_failure(self, domain: str) -> None:
        """Track failure. After 5 consecutive failures, start backing off."""
        key = self._key(domain)
        failures = self._consecutive_failures.get(key, 0) + 1
        self._consecutive_failures[key] = failures

        if failures >= 5:
            # Exponential backoff: 30s, 60s, 120s, 240s, 300s (cap)
            delay = min(30 * (2 ** (failures - 5)), 300)
            self._backoff_until[key] = time.monotonic() + delay

    def get_status(self) -> dict[str, dict]:
        """Get current status of all domains."""
        now = time.monotonic()
        status = {}
        for key in self._base_rates:
            failures = self._consecutive_failures.get(key, 0)
            backoff = self._backoff_until.get(key, 0)
            status[key] = {
                "base_rate_sec": self._base_rates[key],
                "consecutive_failures": failures,
                "backed_off": backoff > now,
                "backoff_remaining_sec": round(max(0, backoff - now), 1),
            }
        return status


rate_limiter = RateLimiter()

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

        if failures >= 3:
            # Fail2ban-style escalation:
            #   3 fails → 30s
            #   5 fails → 2 min
            #   8 fails → 10 min
            #  12 fails → 30 min
            #  20 fails → 1 hour
            #  50+ fails → 6 hours (likely permanently blocked, try once per 6h)
            if failures < 5:
                delay = 30
            elif failures < 8:
                delay = 120
            elif failures < 12:
                delay = 600
            elif failures < 20:
                delay = 1800
            elif failures < 50:
                delay = 3600
            else:
                delay = 21600
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


async def seed_from_db() -> None:
    """Check recent failure rates from enrichment_log and pre-set backoffs."""
    try:
        from brainycat.db import fetch_all

        rows = await fetch_all("""
            SELECT method,
                count(*) FILTER (WHERE NOT success) as recent_fails,
                count(*) FILTER (WHERE success) as recent_ok
            FROM enrichment_log
            WHERE created_at > now() - interval '1 hour'
            GROUP BY method
        """)
        for r in rows:
            if r["recent_fails"] > 10 and r["recent_ok"] == 0:
                rate_limiter._consecutive_failures[r["method"]] = min(r["recent_fails"], 20)
                rate_limiter.report_failure(r["method"])
    except Exception:
        pass

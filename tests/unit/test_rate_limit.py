"""Tests for rate limiter."""

import asyncio
import time

import pytest
from brainycat.rate_limit import RateLimiter


@pytest.mark.asyncio
async def test_rate_limiter_delays() -> None:
    rl = RateLimiter()
    rl._rates = {"default": 0.1}  # 100ms for testing

    start = time.monotonic()
    await rl.wait("test.com")
    await rl.wait("test.com")
    elapsed = time.monotonic() - start

    assert elapsed >= 0.09  # Second call should have waited


@pytest.mark.asyncio
async def test_rate_limiter_domain_specific() -> None:
    rl = RateLimiter()
    rl._rates = {"google": 0.1, "default": 0.05}

    start = time.monotonic()
    await rl.wait("google.com")
    await rl.wait("google.com")
    elapsed = time.monotonic() - start

    assert elapsed >= 0.09  # Should use google rate, not default

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


def test_is_backed_off_false_when_clear() -> None:
    rl = RateLimiter()
    assert rl.is_backed_off("google") is False


def test_is_backed_off_true_during_backoff() -> None:
    rl = RateLimiter()
    for _ in range(3):
        rl.report_failure("google")  # 3 consecutive failures -> 30s backoff
    assert rl.is_backed_off("google") is True


def test_is_backed_off_clears_on_success() -> None:
    rl = RateLimiter()
    for _ in range(3):
        rl.report_failure("google")
    rl.report_success("google")
    assert rl.is_backed_off("google") is False


def test_is_backed_off_does_not_sleep() -> None:
    """Unlike wait(), is_backed_off() must be a plain, instant, non-blocking check."""
    rl = RateLimiter()
    for _ in range(20):
        rl.report_failure("google")  # escalate to a long (1800s+) backoff
    start = time.monotonic()
    assert rl.is_backed_off("google") is True
    assert time.monotonic() - start < 0.05

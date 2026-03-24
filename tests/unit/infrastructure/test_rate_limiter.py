"""Unit tests for RateLimiter.

Uses an in-memory fake Redis so tests run without any external services.
"""
from __future__ import annotations

import pytest

from auth_service.infrastructure.security.rate_limiter import RateLimiter, RateLimitExceededError


# ---------------------------------------------------------------------------
# Fake Redis — minimal in-memory stub
# ---------------------------------------------------------------------------


class FakeRedis:
    """In-memory stub that implements the subset of the Redis API used by RateLimiter."""

    def __init__(self) -> None:
        self._store: dict[str, int] = {}
        self._ttls: dict[str, int] = {}

    async def incr(self, key: str) -> int:
        self._store[key] = self._store.get(key, 0) + 1
        return self._store[key]

    async def expire(self, key: str, seconds: int) -> None:
        self._ttls[key] = seconds

    async def ttl(self, key: str) -> int:
        # Return configured TTL if set, -1 otherwise (no expiry).
        return self._ttls.get(key, -1)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_limiter() -> tuple[RateLimiter, FakeRedis]:
    redis = FakeRedis()
    return RateLimiter(redis), redis


# ---------------------------------------------------------------------------
# check() — core method
# ---------------------------------------------------------------------------


class TestRateLimiterCheck:
    @pytest.mark.asyncio
    async def test_under_limit_passes(self) -> None:
        limiter, _ = make_limiter()
        # 3 requests against a limit of 5 — all must pass
        for i in range(1, 4):
            count = await limiter.check("test_key", limit=5, window_seconds=60)
            assert count == i

    @pytest.mark.asyncio
    async def test_at_limit_passes(self) -> None:
        limiter, _ = make_limiter()
        # Exactly 5 requests against limit=5 — the 5th must still pass
        for _ in range(4):
            await limiter.check("at_limit", limit=5, window_seconds=60)
        count = await limiter.check("at_limit", limit=5, window_seconds=60)
        assert count == 5

    @pytest.mark.asyncio
    async def test_over_limit_raises_429(self) -> None:
        limiter, _ = make_limiter()
        for _ in range(5):
            await limiter.check("over_limit", limit=5, window_seconds=60)
        with pytest.raises(RateLimitExceededError):
            await limiter.check("over_limit", limit=5, window_seconds=60)

    @pytest.mark.asyncio
    async def test_over_limit_sets_retry_after(self) -> None:
        limiter, redis = make_limiter()
        for _ in range(3):
            await limiter.check("retry_key", limit=3, window_seconds=60)
        # Simulate 30 seconds remaining in the window (after window was set).
        redis._ttls["rl:retry_key"] = 30
        with pytest.raises(RateLimitExceededError) as exc_info:
            await limiter.check("retry_key", limit=3, window_seconds=60)
        assert exc_info.value.retry_after == 30

    @pytest.mark.asyncio
    async def test_retry_after_falls_back_to_window_when_ttl_negative(self) -> None:
        limiter, redis = make_limiter()
        # TTL of -1 means no expiry set yet (edge case); should fall back to window.
        for _ in range(2):
            await limiter.check("no_ttl_key", limit=2, window_seconds=120)
        # Force ttl() to return -1 to exercise the fallback branch.
        redis._ttls["rl:no_ttl_key"] = -1
        with pytest.raises(RateLimitExceededError) as exc_info:
            await limiter.check("no_ttl_key", limit=2, window_seconds=120)
        assert exc_info.value.retry_after == 120

    @pytest.mark.asyncio
    async def test_first_request_sets_window_expiry(self) -> None:
        limiter, redis = make_limiter()
        await limiter.check("first_req", limit=10, window_seconds=300)
        assert redis._ttls.get("rl:first_req") == 300

    @pytest.mark.asyncio
    async def test_exceeded_error_carries_key(self) -> None:
        limiter, _ = make_limiter()
        for _ in range(1):
            await limiter.check("my_key", limit=1, window_seconds=60)
        with pytest.raises(RateLimitExceededError) as exc_info:
            await limiter.check("my_key", limit=1, window_seconds=60)
        assert "my_key" in exc_info.value.key


# ---------------------------------------------------------------------------
# check_ip() — convenience wrapper
# ---------------------------------------------------------------------------


class TestRateLimiterCheckIP:
    @pytest.mark.asyncio
    async def test_ip_check_passes_under_limit(self) -> None:
        limiter, _ = make_limiter()
        for _ in range(4):
            await limiter.check_ip("1.2.3.4", "login", limit=5, window_seconds=60)

    @pytest.mark.asyncio
    async def test_ip_check_raises_over_limit(self) -> None:
        limiter, _ = make_limiter()
        for _ in range(5):
            await limiter.check_ip("1.2.3.4", "login", limit=5, window_seconds=60)
        with pytest.raises(RateLimitExceededError):
            await limiter.check_ip("1.2.3.4", "login", limit=5, window_seconds=60)

    @pytest.mark.asyncio
    async def test_different_ips_are_independent(self) -> None:
        limiter, _ = make_limiter()
        for _ in range(5):
            await limiter.check_ip("1.1.1.1", "login", limit=5, window_seconds=60)
        # Different IP — must not be affected by the first IP's counter.
        count = await limiter.check_ip("2.2.2.2", "login", limit=5, window_seconds=60)
        assert count == 1


# ---------------------------------------------------------------------------
# check_email() — convenience wrapper
# ---------------------------------------------------------------------------


class TestRateLimiterCheckEmail:
    @pytest.mark.asyncio
    async def test_email_check_passes_under_limit(self) -> None:
        limiter, _ = make_limiter()
        for _ in range(9):
            await limiter.check_email("user@example.com", "login", limit=10, window_seconds=900)

    @pytest.mark.asyncio
    async def test_email_check_raises_over_limit(self) -> None:
        limiter, _ = make_limiter()
        for _ in range(10):
            await limiter.check_email("user@example.com", "login", limit=10, window_seconds=900)
        with pytest.raises(RateLimitExceededError):
            await limiter.check_email("user@example.com", "login", limit=10, window_seconds=900)

    @pytest.mark.asyncio
    async def test_email_normalised_to_lowercase(self) -> None:
        limiter, redis = make_limiter()
        # Mixed-case and lowercase should share the same counter.
        await limiter.check_email("User@Example.COM", "login", limit=10, window_seconds=60)
        await limiter.check_email("user@example.com", "login", limit=10, window_seconds=60)
        redis_key = "rl:login:email:user@example.com"
        assert redis._store.get(redis_key) == 2

    @pytest.mark.asyncio
    async def test_different_emails_are_independent(self) -> None:
        limiter, _ = make_limiter()
        for _ in range(3):
            await limiter.check_email("alice@example.com", "reset", limit=3, window_seconds=3600)
        # alice is exhausted; bob must still pass.
        count = await limiter.check_email("bob@example.com", "reset", limit=3, window_seconds=3600)
        assert count == 1

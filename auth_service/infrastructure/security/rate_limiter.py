"""Rate limiting for the auth service using Redis fixed-window counters.

Rate limiting uses a Redis-backed fixed-window approach integrated with SlowAPI
(FastAPI-native) for HTTP 429 exception handling infrastructure.  Per-operation
limits are enforced via RateLimiter using the existing async Redis connection.

Account lockout deliberately NOT implemented.
Rationale: hard account lockout enables a DoS attack — any attacker who knows a
victim's email can intentionally exceed the limit and lock the legitimate user out.
Exponential back-off via rate limits (HTTP 429 + Retry-After) prevents sustained
brute force without creating this DoS vector.  If the threat model changes to
require account lockout (e.g., PCI-DSS Level 1 compliance), add it as a separate,
audited control rather than modifying this module.

Two-dimensional limits (per IP + per email/key) catch both volumetric attacks
(IP-level flooding) and targeted attacks (credential stuffing against a single
account).
"""
from __future__ import annotations

import redis.asyncio as aioredis
import structlog

logger = structlog.get_logger(__name__)


class RateLimitExceededError(Exception):
    """Raised when a rate limit is exceeded.

    Attributes:
        retry_after: Seconds until the rate limit window resets.
        key: The rate limit key that was exceeded (for logging).
    """

    def __init__(self, retry_after: int, key: str = "") -> None:
        self.retry_after = retry_after
        self.key = key
        super().__init__(f"Rate limit exceeded. Retry after {retry_after} seconds.")


class RateLimiter:
    """Fixed-window rate limiter backed by Redis.

    Uses Redis INCR + EXPIRE for atomic per-window counting.

    Fixed window trade-off: a client can burst up to 2× the limit by straddling
    a window boundary.  For auth rate limiting — where the goal is to stop
    sustained brute-force, not short bursts — this is acceptable and far simpler
    than a sliding-window (sorted-set) approach.

    Usage::

        limiter = RateLimiter(redis_client)

        # IP-based limit: 5 login attempts per minute per IP
        await limiter.check_ip(ip, "login", limit=5, window_seconds=60)

        # Email-keyed limit: 10 login attempts per 15 min per email
        await limiter.check_email(email, "login", limit=10, window_seconds=900)
    """

    def __init__(self, redis_client: aioredis.Redis) -> None:
        self._redis = redis_client

    async def check(self, key: str, limit: int, window_seconds: int) -> int:
        """Increment the counter for *key* and enforce *limit*.

        Args:
            key: Unique rate-limit key (must NOT include the ``rl:`` prefix).
            limit: Maximum allowed requests within *window_seconds*.
            window_seconds: Length of the counting window.

        Returns:
            The current request count within this window.

        Raises:
            RateLimitExceededError: when the count exceeds *limit*.
        """
        redis_key = f"rl:{key}"

        # SET NX EX initialises the key with value "0" and a TTL atomically.
        # This ensures the TTL is always set before the first INCR, eliminating
        # the race condition where the key could exist without an expiry if the
        # process crashes between INCR and EXPIRE.
        await self._redis.set(redis_key, 0, ex=window_seconds, nx=True)
        count = await self._redis.incr(redis_key)

        if count > limit:
            ttl = await self._redis.ttl(redis_key)
            retry_after = ttl if ttl > 0 else window_seconds
            logger.warning(
                "rate_limit_exceeded",
                key=key,
                count=count,
                limit=limit,
                retry_after=retry_after,
            )
            raise RateLimitExceededError(retry_after=retry_after, key=key)

        return count

    async def check_ip(
        self, ip: str, operation: str, limit: int, window_seconds: int
    ) -> int:
        """IP-based rate limit check."""
        return await self.check(f"{operation}:ip:{ip}", limit, window_seconds)

    async def check_email(
        self, email: str, operation: str, limit: int, window_seconds: int
    ) -> int:
        """Email-keyed rate limit check — normalises the address to lowercase."""
        normalized = email.lower().strip()
        return await self.check(f"{operation}:email:{normalized}", limit, window_seconds)

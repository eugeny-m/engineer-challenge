"""Redis-backed idempotency store for preventing duplicate side effects on retries."""
import json

import redis.asyncio as aioredis


class IdempotencyStore:
    """Store and retrieve idempotency records in Redis.

    Key format:  idempotency:{operation}:{idempotency_key_value}
    Value format: {"request_hash": "<sha256>", "response": {...}}
    TTL: 24 hours (86400s) by default.
    """

    def __init__(self, redis_client: aioredis.Redis) -> None:
        self._redis = redis_client

    @staticmethod
    def _key(operation: str, idempotency_key: str) -> str:
        return f"idempotency:{operation}:{idempotency_key}"

    async def get(self, key: str) -> dict | None:
        """Fetch and JSON-decode an idempotency record. Returns None on cache miss."""
        raw = await self._redis.get(key)
        if raw is None:
            return None
        if isinstance(raw, bytes):
            raw = raw.decode()
        return json.loads(raw)

    async def set(self, key: str, value: dict, ttl: int = 86400) -> None:
        """JSON-encode and store an idempotency record with the given TTL (seconds)."""
        await self._redis.setex(key, ttl, json.dumps(value))

    def make_key(self, operation: str, idempotency_key: str) -> str:
        """Build the canonical Redis key for an idempotency record."""
        return self._key(operation, idempotency_key)

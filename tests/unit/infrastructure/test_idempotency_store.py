"""Unit tests for IdempotencyStore with a mocked Redis client."""
from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from auth_service.infrastructure.redis.idempotency_store import IdempotencyStore


def _make_store() -> tuple[IdempotencyStore, MagicMock]:
    redis_client = MagicMock()
    redis_client.get = AsyncMock()
    redis_client.setex = AsyncMock()
    return IdempotencyStore(redis_client), redis_client


class TestIdempotencyStoreGet:
    @pytest.mark.asyncio
    async def test_get_miss_returns_none(self) -> None:
        store, redis_client = _make_store()
        redis_client.get.return_value = None

        result = await store.get("idempotency:login:some-key")

        assert result is None
        redis_client.get.assert_awaited_once_with("idempotency:login:some-key")

    @pytest.mark.asyncio
    async def test_get_hit_returns_dict(self) -> None:
        store, redis_client = _make_store()
        stored = {"request_hash": "abc123", "response": {"data": {"login": {"token": "t"}}}}
        redis_client.get.return_value = json.dumps(stored).encode()

        result = await store.get("idempotency:login:some-key")

        assert result == stored

    @pytest.mark.asyncio
    async def test_get_hit_returns_dict_from_str(self) -> None:
        store, redis_client = _make_store()
        stored = {"request_hash": "xyz", "response": {"data": {}}}
        redis_client.get.return_value = json.dumps(stored)

        result = await store.get("idempotency:login:my-key")

        assert result == stored


class TestIdempotencyStoreSet:
    @pytest.mark.asyncio
    async def test_set_calls_setex_with_correct_key_and_ttl(self) -> None:
        store, redis_client = _make_store()
        value = {"request_hash": "hash1", "response": {"data": {}}}
        key = "idempotency:login:my-key"

        await store.set(key, value, ttl=86400)

        redis_client.setex.assert_awaited_once_with(key, 86400, json.dumps(value))

    @pytest.mark.asyncio
    async def test_set_uses_default_ttl_of_24h(self) -> None:
        store, redis_client = _make_store()
        value = {"request_hash": "h", "response": {}}
        key = "idempotency:requestPasswordReset:k"

        await store.set(key, value)

        call_args = redis_client.setex.call_args
        assert call_args[0][1] == 86400  # TTL is second positional arg

    @pytest.mark.asyncio
    async def test_set_stores_json_encoded_value(self) -> None:
        store, redis_client = _make_store()
        value = {"request_hash": "abc", "response": {"nested": {"a": 1}}}
        key = "idempotency:login:k"

        await store.set(key, value)

        stored_json = redis_client.setex.call_args[0][2]
        assert json.loads(stored_json) == value


class TestIdempotencyStoreMakeKey:
    def test_make_key_format(self) -> None:
        store, _ = _make_store()
        key = store.make_key("login", "abc-123")
        assert key == "idempotency:login:abc-123"

    def test_make_key_request_password_reset(self) -> None:
        store, _ = _make_store()
        key = store.make_key("requestPasswordReset", "my-uuid")
        assert key == "idempotency:requestPasswordReset:my-uuid"

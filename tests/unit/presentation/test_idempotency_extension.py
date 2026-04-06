"""Unit tests for IdempotencyExtension."""
from __future__ import annotations

import hashlib
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from graphql import parse

from auth_service.infrastructure.redis.idempotency_store import IdempotencyStore
from auth_service.presentation.graphql.idempotency import (
    IDEMPOTENT_OPERATIONS,
    IdempotencyExtension,
)
from strawberry.types import ExecutionResult


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_store(cached_value=None) -> tuple[IdempotencyStore, MagicMock]:
    redis_client = MagicMock()
    redis_client.get = AsyncMock(return_value=None)
    redis_client.setex = AsyncMock()
    store = IdempotencyStore(redis_client)
    if cached_value is not None:
        import json as _json
        redis_client.get.return_value = _json.dumps(cached_value).encode()
    return store, redis_client


def _make_request(idempotency_key: str | None = "test-key-123") -> MagicMock:
    request = MagicMock()
    headers: dict[str, str] = {}
    if idempotency_key is not None:
        headers["Idempotency-Key"] = idempotency_key
    request.headers = headers
    return request


def _make_execution_context(
    operation_name: str = "login",
    variables: dict | None = None,
    idempotency_key: str | None = "test-key-123",
    result: ExecutionResult | None = None,
) -> MagicMock:
    doc = parse(f"mutation {{ {operation_name}(input: {{}}) {{ __typename }} }}")
    ctx = MagicMock()
    ctx.graphql_document = doc
    ctx.variables = variables or {}
    ctx.context = {"request": _make_request(idempotency_key)}
    ctx.result = result
    return ctx


def _build_extension(
    operation_name: str = "login",
    variables: dict | None = None,
    idempotency_key: str | None = "test-key-123",
    cached_value=None,
    result: ExecutionResult | None = None,
) -> tuple[IdempotencyExtension, MagicMock, MagicMock]:
    store, redis_client = _make_store(cached_value)
    execution_ctx = _make_execution_context(
        operation_name=operation_name,
        variables=variables,
        idempotency_key=idempotency_key,
        result=result,
    )
    ConfiguredExt = IdempotencyExtension.with_store(store)
    ext = ConfiguredExt(execution_context=execution_ctx)
    return ext, execution_ctx, redis_client


def _compute_hash(operation_name: str, variables: dict) -> str:
    return hashlib.sha256(
        (operation_name + json.dumps(variables, sort_keys=True)).encode()
    ).hexdigest()


# ---------------------------------------------------------------------------
# Tests: cache miss → execute and store
# ---------------------------------------------------------------------------


class TestCacheMiss:
    @pytest.mark.asyncio
    async def test_cache_miss_yields_to_execute_handler(self) -> None:
        ext, ctx, redis_client = _build_extension(cached_value=None)
        redis_client.get.return_value = None

        gen = ext.on_execute()
        await gen.__anext__()  # pre-execute phase

        # execution_context.result is still None/unset — handler should run
        assert ctx.result is None

    @pytest.mark.asyncio
    async def test_cache_miss_stores_result_after_execution(self) -> None:
        ext, ctx, redis_client = _build_extension(cached_value=None)
        redis_client.get.return_value = None

        gen = ext.on_execute()
        await gen.__anext__()  # pre-execute phase

        # Simulate execution setting the result
        ctx.result = ExecutionResult(data={"login": {"accessToken": "tok"}}, errors=None)

        with pytest.raises(StopAsyncIteration):
            await gen.__anext__()  # post-execute phase

        # Result should have been persisted
        redis_client.setex.assert_awaited_once()
        call_args = redis_client.setex.call_args[0]
        stored = json.loads(call_args[2])
        assert stored["response"] == {"login": {"accessToken": "tok"}}
        assert "request_hash" in stored

    @pytest.mark.asyncio
    async def test_cache_miss_does_not_store_if_errors(self) -> None:
        from graphql import GraphQLError

        ext, ctx, redis_client = _build_extension(cached_value=None)
        redis_client.get.return_value = None

        gen = ext.on_execute()
        await gen.__anext__()

        ctx.result = ExecutionResult(
            data=None,
            errors=[GraphQLError("some error")],
        )

        with pytest.raises(StopAsyncIteration):
            await gen.__anext__()

        redis_client.setex.assert_not_awaited()


# ---------------------------------------------------------------------------
# Tests: cache hit with matching hash → return cached response
# ---------------------------------------------------------------------------


class TestCacheHitMatchingHash:
    @pytest.mark.asyncio
    async def test_cache_hit_matching_hash_sets_cached_result(self) -> None:
        variables: dict = {}
        expected_hash = _compute_hash("login", variables)
        cached = {
            "request_hash": expected_hash,
            "response": {"login": {"accessToken": "cached-tok"}},
        }
        ext, ctx, redis_client = _build_extension(cached_value=cached, variables=variables)

        gen = ext.on_execute()
        await gen.__anext__()  # pre-execute: should inject cached result

        # execution_context.result must be set with cached data
        assert ctx.result is not None
        assert ctx.result.data == {"login": {"accessToken": "cached-tok"}}
        assert ctx.result.errors is None

    @pytest.mark.asyncio
    async def test_cache_hit_matching_hash_generator_finishes_after_yield(self) -> None:
        variables: dict = {}
        expected_hash = _compute_hash("login", variables)
        cached = {
            "request_hash": expected_hash,
            "response": {"login": {"accessToken": "cached-tok"}},
        }
        ext, ctx, redis_client = _build_extension(cached_value=cached, variables=variables)

        gen = ext.on_execute()
        await gen.__anext__()

        with pytest.raises(StopAsyncIteration):
            await gen.__anext__()

    @pytest.mark.asyncio
    async def test_cache_hit_matching_hash_does_not_re_store(self) -> None:
        variables: dict = {}
        expected_hash = _compute_hash("login", variables)
        cached = {
            "request_hash": expected_hash,
            "response": {"login": {"accessToken": "cached-tok"}},
        }
        ext, ctx, redis_client = _build_extension(cached_value=cached, variables=variables)

        gen = ext.on_execute()
        await gen.__anext__()
        with pytest.raises(StopAsyncIteration):
            await gen.__anext__()

        # Must NOT write to Redis again
        redis_client.setex.assert_not_awaited()


# ---------------------------------------------------------------------------
# Tests: cache hit with different hash → IDEMPOTENCY_CONFLICT
# ---------------------------------------------------------------------------


class TestCacheHitConflict:
    @pytest.mark.asyncio
    async def test_conflict_sets_error_result(self) -> None:
        # Store has hash for empty variables; we send different variables
        cached_hash = _compute_hash("login", {"different": "body"})
        cached = {
            "request_hash": cached_hash,
            "response": {"login": {"accessToken": "old-tok"}},
        }
        # ext uses empty variables → hash mismatch
        ext, ctx, redis_client = _build_extension(cached_value=cached, variables={})

        gen = ext.on_execute()
        await gen.__anext__()

        assert ctx.result is not None
        assert ctx.result.data is None
        assert ctx.result.errors is not None
        assert len(ctx.result.errors) == 1
        error = ctx.result.errors[0]
        assert "Idempotency key reused" in str(error.message)
        assert error.extensions == {"code": "IDEMPOTENCY_CONFLICT"}

    @pytest.mark.asyncio
    async def test_conflict_does_not_store(self) -> None:
        cached_hash = _compute_hash("login", {"different": "body"})
        cached = {"request_hash": cached_hash, "response": {}}
        ext, ctx, redis_client = _build_extension(cached_value=cached, variables={})

        gen = ext.on_execute()
        await gen.__anext__()
        with pytest.raises(StopAsyncIteration):
            await gen.__anext__()

        redis_client.setex.assert_not_awaited()


# ---------------------------------------------------------------------------
# Tests: skip logic (non-idempotent operations, missing header)
# ---------------------------------------------------------------------------


class TestSkipConditions:
    @pytest.mark.asyncio
    async def test_non_idempotent_operation_skips_cache(self) -> None:
        ext, ctx, redis_client = _build_extension(operation_name="register")

        gen = ext.on_execute()
        await gen.__anext__()
        with pytest.raises(StopAsyncIteration):
            await gen.__anext__()

        redis_client.get.assert_not_awaited()
        redis_client.setex.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_missing_idempotency_key_skips_cache(self) -> None:
        ext, ctx, redis_client = _build_extension(idempotency_key=None)

        gen = ext.on_execute()
        await gen.__anext__()
        with pytest.raises(StopAsyncIteration):
            await gen.__anext__()

        redis_client.get.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_request_password_reset_is_idempotent(self) -> None:
        """requestPasswordReset must be in IDEMPOTENT_OPERATIONS."""
        assert "requestPasswordReset" in IDEMPOTENT_OPERATIONS

    @pytest.mark.asyncio
    async def test_login_is_idempotent(self) -> None:
        assert "login" in IDEMPOTENT_OPERATIONS


# ---------------------------------------------------------------------------
# Tests: _get_mutation_field_name helper
# ---------------------------------------------------------------------------


class TestGetMutationFieldName:
    def _make_ext(self, query: str) -> IdempotencyExtension:
        store, _ = _make_store()
        ConfiguredExt = IdempotencyExtension.with_store(store)
        ctx = MagicMock()
        ctx.graphql_document = parse(query)
        ctx.variables = {}
        ctx.context = {}
        ctx.result = None
        return ConfiguredExt(execution_context=ctx)

    def test_extracts_login_field(self) -> None:
        ext = self._make_ext("mutation { login(input: {}) { accessToken } }")
        assert ext._get_mutation_field_name() == "login"

    def test_extracts_request_password_reset_field(self) -> None:
        ext = self._make_ext("mutation { requestPasswordReset(input: {}) { success } }")
        assert ext._get_mutation_field_name() == "requestPasswordReset"

    def test_returns_none_for_query(self) -> None:
        ext = self._make_ext("{ __typename }")
        assert ext._get_mutation_field_name() is None

    def test_returns_none_for_no_document(self) -> None:
        store, _ = _make_store()
        ConfiguredExt = IdempotencyExtension.with_store(store)
        ctx = MagicMock()
        ctx.graphql_document = None
        ctx.variables = {}
        ctx.context = {}
        ctx.result = None
        ext = ConfiguredExt(execution_context=ctx)
        assert ext._get_mutation_field_name() is None

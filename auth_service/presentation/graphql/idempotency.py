"""Strawberry SchemaExtension that enforces idempotency for selected mutations."""
from __future__ import annotations

import hashlib
import json
from typing import TYPE_CHECKING, AsyncIterator

from graphql import GraphQLError, OperationType
from graphql.language import FieldNode, OperationDefinitionNode
from strawberry.extensions import SchemaExtension
from strawberry.types import ExecutionContext, ExecutionResult

from auth_service.infrastructure.redis.idempotency_store import IdempotencyStore

if TYPE_CHECKING:
    pass

IDEMPOTENT_OPERATIONS: frozenset[str] = frozenset({"login", "requestPasswordReset"})


class IdempotencyExtension(SchemaExtension):
    """Prevent duplicate side effects on client retries for idempotent mutations.

    Clients send an ``Idempotency-Key`` header with a unique value per logical
    request.  When the same key is re-submitted with the same request body the
    cached response is returned without re-executing the mutation.  A different
    body with the same key results in an ``IDEMPOTENCY_CONFLICT`` GraphQL error.
    """

    _store: IdempotencyStore

    def __init__(self, *, execution_context: ExecutionContext) -> None:
        # Strawberry normally sets execution_context externally after __init__,
        # but we store it here too so the extension works when constructed directly
        # in tests or other non-schema contexts.
        self.execution_context = execution_context
        # _store is injected by with_store(); callers must use that factory.

    @classmethod
    def with_store(cls, store: IdempotencyStore) -> type[IdempotencyExtension]:
        """Return a configured subclass with the given IdempotencyStore bound."""

        class _Configured(cls):  # type: ignore[valid-type]
            def __init__(self, *, execution_context: ExecutionContext) -> None:
                super().__init__(execution_context=execution_context)
                self._store = store

        _Configured.__name__ = cls.__name__
        _Configured.__qualname__ = cls.__qualname__
        return _Configured  # type: ignore[return-value]

    # ------------------------------------------------------------------
    # Lifecycle hook
    # ------------------------------------------------------------------

    async def on_execute(self) -> AsyncIterator[None]:  # type: ignore[override]
        operation_name = self._get_mutation_field_name()
        if operation_name not in IDEMPOTENT_OPERATIONS:
            yield
            return

        request = (self.execution_context.context or {}).get("request")
        idempotency_key: str | None = None
        if request is not None:
            idempotency_key = request.headers.get("Idempotency-Key")

        if not idempotency_key:
            yield
            return

        variables = self.execution_context.variables or {}
        request_hash = hashlib.sha256(
            (operation_name + json.dumps(variables, sort_keys=True)).encode()
        ).hexdigest()

        redis_key = self._store.make_key(operation_name, idempotency_key)
        cached = await self._store.get(redis_key)

        if cached is not None:
            if cached.get("request_hash") == request_hash:
                # Return cached response without executing the mutation.
                self.execution_context.result = ExecutionResult(
                    data=cached["response"],
                    errors=None,
                )
            else:
                # Same key, different body — conflict.
                self.execution_context.result = ExecutionResult(
                    data=None,
                    errors=[
                        GraphQLError(
                            "Idempotency key reused with different request",
                            extensions={"code": "IDEMPOTENCY_CONFLICT"},
                        )
                    ],
                )
            yield
            return

        # Cache miss — execute normally.
        yield

        # After execution: persist the result for future retries.
        result = self.execution_context.result
        if result is not None and not result.errors and result.data is not None:
            await self._store.set(
                redis_key,
                {"request_hash": request_hash, "response": result.data},
            )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _get_mutation_field_name(self) -> str | None:
        """Return the first mutation field name from the parsed document, or None."""
        doc = self.execution_context.graphql_document
        if doc is None:
            return None
        for definition in doc.definitions:
            if not isinstance(definition, OperationDefinitionNode):
                continue
            if definition.operation is not OperationType.MUTATION:
                continue
            selections = definition.selection_set.selections if definition.selection_set else []
            for selection in selections:
                if isinstance(selection, FieldNode):
                    return selection.name.value
        return None

"""FastAPI application entry point."""
from __future__ import annotations

import json
import os
import re
from contextlib import asynccontextmanager
from typing import AsyncGenerator

import redis.asyncio as aioredis
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp

from auth_service.container import GlobalContainer, set_global_container, get_global_container
from auth_service.infrastructure.db.session import async_session_factory
from auth_service.infrastructure.logging import configure_logging
from auth_service.infrastructure.security.rate_limiter import RateLimiter, RateLimitExceededError
from auth_service.presentation.graphql.schema import create_graphql_router

# ---------------------------------------------------------------------------
# Rate limit rules (operation → list of (dimension, limit, window_seconds))
# ---------------------------------------------------------------------------
# Account lockout deliberately NOT implemented — see rate_limiter.py for rationale.
_RATE_LIMITS: dict[str, list[tuple[str, int, int]]] = {
    #                                    dimension   limit   window_sec
    "login": [
        ("ip", 5, 60),         # 5 / IP / minute        (credential stuffing)
        ("email", 10, 900),    # 10 / email / 15 min    (targeted brute force)
    ],
    "register": [
        ("ip", 5, 3600),       # 5 / IP / hour          (spam account creation)
    ],
    "requestPasswordReset": [
        ("email", 3, 3600),    # 3 / email / hour       (email bombing)
        ("ip", 10, 3600),      # 10 / IP / hour         (enumeration)
    ],
    "resetPassword": [
        ("ip", 10, 3600),      # 10 / IP / hour         (defense in depth; token is 256-bit)
    ],
    "refreshToken": [
        ("ip", 60, 3600),      # 60 / IP / hour         (mild abuse prevention)
    ],
}

# Regex to extract the first mutation field name from a GraphQL query string.
_MUTATION_OP_RE = re.compile(r"mutation\b[^{]*\{[^{]*?(\w+)\s*[\({]", re.DOTALL)

# Fields that carry an email in their variables (variables.input.email)
_EMAIL_OPS = frozenset({"login", "register", "requestPasswordReset"})


class GraphQLRateLimitMiddleware(BaseHTTPMiddleware):
    """Starlette middleware that enforces per-operation rate limits on /graphql.

    Reads the raw request body once (Starlette caches it for downstream use),
    extracts the GraphQL operation name and email from input variables, then
    applies the configured limits via RateLimiter.  Returns HTTP 429 with a
    Retry-After header if any limit is exceeded.
    """

    def __init__(self, app: ASGIApp) -> None:
        super().__init__(app)

    async def dispatch(self, request: Request, call_next):  # type: ignore[override]
        if request.url.path not in ("/graphql", "/graphql/") or request.method != "POST":
            return await call_next(request)

        # get_global_container may raise before lifespan completes (e.g. in tests).
        try:
            container = get_global_container()
            rate_limiter: RateLimiter = container.rate_limiter
        except RuntimeError:
            return await call_next(request)

        body_bytes = await request.body()
        try:
            body = json.loads(body_bytes)
        except (json.JSONDecodeError, ValueError):
            return await call_next(request)

        operation = self._extract_operation(body)
        if operation not in _RATE_LIMITS:
            return await call_next(request)

        # Prefer X-Real-IP set by trusted reverse proxies; fall back to X-Forwarded-For
        # (first entry is the originating client), then the transport-level address.
        ip = (
            request.headers.get("x-real-ip")
            or (request.headers.get("x-forwarded-for", "").split(",")[0].strip() or None)
            or (request.client.host if request.client else None)
            or "unknown"
        )
        email = self._extract_email(body) if operation in _EMAIL_OPS else None

        for dimension, limit, window in _RATE_LIMITS[operation]:
            try:
                if dimension == "ip":
                    await rate_limiter.check_ip(ip, operation, limit, window)
                elif dimension == "email" and email:
                    await rate_limiter.check_email(email, operation, limit, window)
            except RateLimitExceededError as exc:
                return JSONResponse(
                    status_code=429,
                    content={"errors": [{"message": "Rate limit exceeded"}]},
                    headers={"Retry-After": str(exc.retry_after)},
                )

        return await call_next(request)

    @staticmethod
    def _extract_operation(body: dict) -> str:
        """Return the first mutation field name from a GraphQL request body."""
        query: str = body.get("query", "")
        match = _MUTATION_OP_RE.search(query)
        if match:
            return match.group(1)
        # Do NOT fall back to body["operationName"]: it is user-supplied and could
        # be any string that does not correspond to the actual mutation field name,
        # allowing callers to bypass per-operation rate limits.
        return ""

    @staticmethod
    def _extract_email(body: dict) -> str | None:
        """Extract email from GraphQL input variables (variables.input.email)."""
        variables = body.get("variables") or {}
        input_obj = variables.get("input") or {}
        return input_obj.get("email") or variables.get("email")


# ---------------------------------------------------------------------------
# Application factory
# ---------------------------------------------------------------------------


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Initialise and tear down app-lifetime resources."""
    configure_logging()
    redis_url = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
    redis_client = aioredis.from_url(redis_url, decode_responses=False)

    container = GlobalContainer(
        redis_client=redis_client,
        session_factory=async_session_factory,
    )
    set_global_container(container)

    yield

    await redis_client.aclose()


async def get_context(request: Request) -> AsyncGenerator[dict, None]:
    """Per-request GraphQL context — opens a DB session for the duration."""
    global_container = get_global_container()
    async with global_container.request_scope() as scope:
        yield {"request": request, "container": scope}


app = FastAPI(title="Auth Service", lifespan=lifespan)

# GraphQL-aware rate limiting middleware (per-operation + email-keyed).
app.add_middleware(GraphQLRateLimitMiddleware)

graphql_router = create_graphql_router(get_context)
app.include_router(graphql_router, prefix="/graphql")

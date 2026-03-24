"""FastAPI application entry point."""
from __future__ import annotations

import os
from contextlib import asynccontextmanager
from typing import AsyncGenerator

import redis.asyncio as aioredis
from fastapi import FastAPI, Request

from auth_service.container import GlobalContainer, set_global_container, get_global_container
from auth_service.infrastructure.db.session import async_session_factory
from auth_service.infrastructure.logging import configure_logging
from auth_service.presentation.graphql.schema import create_graphql_router


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

graphql_router = create_graphql_router(get_context)
app.include_router(graphql_router, prefix="/graphql")

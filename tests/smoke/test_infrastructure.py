"""Smoke tests: verify postgres and redis are reachable.

Run these against a live Docker Compose environment:
    docker compose -f docker/docker-compose.yml up -d
    pytest tests/smoke/ -v

These tests are skipped automatically when the services are not available.
"""
import os
import socket
from urllib.parse import urlparse

import pytest


def _is_port_open(host: str, port: int, timeout: float = 1.0) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


_db_url = os.environ.get("DB_URL", "postgresql+asyncpg://localhost:5432/auth")
_parsed_pg = urlparse(_db_url)
POSTGRES_HOST = _parsed_pg.hostname or "localhost"
POSTGRES_PORT = _parsed_pg.port or 5432

_redis_url = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
_parsed_redis = urlparse(_redis_url)
REDIS_HOST = _parsed_redis.hostname or "localhost"
REDIS_PORT = _parsed_redis.port or 6379

postgres_available = pytest.mark.skipif(
    not _is_port_open(POSTGRES_HOST, POSTGRES_PORT),
    reason=f"PostgreSQL not reachable at {POSTGRES_HOST}:{POSTGRES_PORT}",
)
redis_available = pytest.mark.skipif(
    not _is_port_open(REDIS_HOST, REDIS_PORT),
    reason=f"Redis not reachable at {REDIS_HOST}:{REDIS_PORT}",
)


@postgres_available
@pytest.mark.smoke
async def test_postgres_reachable():
    """Verify PostgreSQL is reachable and both databases exist."""
    import asyncpg

    db_url_raw = os.environ.get(
        "DB_URL",
        f"postgresql://auth_user:auth_password@{POSTGRES_HOST}:{POSTGRES_PORT}/auth",
    ).replace("postgresql+asyncpg://", "postgresql://")

    conn = await asyncpg.connect(dsn=db_url_raw)
    try:
        result = await conn.fetchval("SELECT 1")
        assert result == 1

        # Check auth_test database exists
        exists = await conn.fetchval(
            "SELECT 1 FROM pg_database WHERE datname = 'auth_test'"
        )
        assert exists == 1, "auth_test database must exist (created by init.sql)"
    finally:
        await conn.close()


@redis_available
@pytest.mark.smoke
async def test_redis_ping():
    """Verify Redis is reachable and responds to PING."""
    import redis.asyncio as aioredis

    redis_url = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
    client = aioredis.from_url(redis_url)
    try:
        result = await client.ping()
        assert result is True, "Redis PING must return PONG (True)"
    finally:
        await client.aclose()

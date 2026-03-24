"""Smoke tests: verify postgres and redis are reachable.

Run these against a live Docker Compose environment:
    docker compose -f docker/docker-compose.yml up -d
    pytest tests/smoke/ -v

These tests are skipped automatically when the services are not available.
"""
import os
import socket

import pytest


def _is_port_open(host: str, port: int, timeout: float = 1.0) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


POSTGRES_HOST = os.environ.get("POSTGRES_HOST", "localhost")
POSTGRES_PORT = int(os.environ.get("POSTGRES_PORT", "5432"))
REDIS_HOST = os.environ.get("REDIS_HOST", "localhost")
REDIS_PORT = int(os.environ.get("REDIS_PORT", "6379"))

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

    redis_url = os.environ.get("REDIS_URL", f"redis://{REDIS_HOST}:{REDIS_PORT}/0")
    client = aioredis.from_url(redis_url)
    try:
        result = await client.ping()
        assert result is True, "Redis PING must return PONG (True)"
    finally:
        await client.aclose()

"""Integration tests for the GraphQL API — require PostgreSQL + Redis."""
from __future__ import annotations

import os
import socket
import uuid
from contextlib import asynccontextmanager
from typing import AsyncGenerator
from urllib.parse import urlparse

import pytest
import pytest_asyncio
from fastapi import FastAPI, Request
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import redis.asyncio as aioredis

from auth_service.container import GlobalContainer, set_global_container
from auth_service.infrastructure.db.models import Base
from auth_service.presentation.graphql.schema import create_graphql_router

pytestmark = pytest.mark.integration

# ---------------------------------------------------------------------------
# Availability checks
# ---------------------------------------------------------------------------

_TEST_DB_URL = os.environ.get(
    "DB_TEST_URL",
    "postgresql+asyncpg://auth_user:auth_password@postgres:5432/auth_test",
)
_REDIS_URL = os.environ.get("REDIS_TEST_URL", "redis://redis:6379/2")


def _port_open(host: str, port: int) -> bool:
    try:
        with socket.create_connection((host, port), timeout=1):
            return True
    except OSError:
        return False


_parsed_db = urlparse(_TEST_DB_URL)
_db_host = _parsed_db.hostname or "localhost"
_db_port = _parsed_db.port or 5432
_parsed_redis = urlparse(_REDIS_URL)
_redis_host = _parsed_redis.hostname or "localhost"
_redis_port = _parsed_redis.port or 6379
_db_available = _port_open(_db_host, _db_port)
_redis_available = _port_open(_redis_host, _redis_port)
_services_available = _db_available and _redis_available

skip_no_services = pytest.mark.skipif(
    not _services_available,
    reason="PostgreSQL or Redis not available (no Docker in CI)",
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest_asyncio.fixture(scope="module")
async def test_engine():
    if not _db_available:
        pytest.skip("PostgreSQL not available")
    engine = create_async_engine(_TEST_DB_URL, echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


@pytest_asyncio.fixture(scope="module")
async def redis_client():
    if not _redis_available:
        pytest.skip("Redis not available")
    client = aioredis.from_url(_REDIS_URL, decode_responses=False)
    yield client
    await client.flushdb()
    await client.aclose()


@pytest_asyncio.fixture
async def test_session_factory(test_engine):
    return async_sessionmaker(test_engine, expire_on_commit=False, class_=AsyncSession)


@pytest_asyncio.fixture
async def test_client(test_session_factory, redis_client):
    """Create a test FastAPI app wired to test DB + Redis."""
    async def get_context(request: Request) -> AsyncGenerator[dict, None]:
        async with container.request_scope() as scope:
            yield {"request": request, "container": scope}

    # Set JWT secret before creating container (container reads it in __init__)
    os.environ.setdefault("JWT_SECRET", "test-secret-key")

    container = GlobalContainer(
        redis_client=redis_client,
        session_factory=test_session_factory,
    )

    app = FastAPI()
    graphql_router = create_graphql_router(get_context)
    app.include_router(graphql_router, prefix="/graphql")

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        yield client, container


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def gql(query: str, variables: dict | None = None) -> dict:
    body: dict = {"query": query}
    if variables:
        body["variables"] = variables
    return body


REGISTER_MUTATION = """
mutation Register($email: String!, $password: String!) {
  register(input: {email: $email, password: $password}) {
    success
    message
  }
}
"""

LOGIN_MUTATION = """
mutation Login($email: String!, $password: String!) {
  login(input: {email: $email, password: $password}) {
    accessToken
    refreshToken
    sessionId
    tokenType
  }
}
"""

REFRESH_MUTATION = """
mutation Refresh($token: String!) {
  refreshToken(input: {refreshToken: $token}) {
    accessToken
    refreshToken
    sessionId
    tokenType
  }
}
"""

REVOKE_MUTATION = """
mutation Revoke($sessionId: ID!) {
  revokeSession(input: {sessionId: $sessionId}) {
    success
    message
  }
}
"""

REQUEST_RESET_MUTATION = """
mutation RequestReset($email: String!) {
  requestPasswordReset(input: {email: $email}) {
    success
    message
  }
}
"""

RESET_PASSWORD_MUTATION = """
mutation ResetPassword($token: String!, $newPassword: String!) {
  resetPassword(input: {token: $token, newPassword: $newPassword}) {
    success
    message
  }
}
"""

ME_QUERY = """
query Me {
  me {
    id
    email
    isActive
  }
}
"""


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

@skip_no_services
class TestRegister:
    async def test_register_success(self, test_client):
        client, _ = test_client
        email = f"reg-{uuid.uuid4().hex[:8]}@example.com"
        resp = await client.post(
            "/graphql",
            json=gql(REGISTER_MUTATION, {"email": email, "password": "SecurePass1"}),
        )
        assert resp.status_code == 200
        data = resp.json()["data"]["register"]
        assert data["success"] is True

    async def test_register_duplicate(self, test_client):
        client, _ = test_client
        email = f"dup-{uuid.uuid4().hex[:8]}@example.com"
        await client.post(
            "/graphql",
            json=gql(REGISTER_MUTATION, {"email": email, "password": "SecurePass1"}),
        )
        resp = await client.post(
            "/graphql",
            json=gql(REGISTER_MUTATION, {"email": email, "password": "SecurePass1"}),
        )
        data = resp.json()["data"]["register"]
        assert data["success"] is False
        assert "could not be completed" in data["message"].lower()

    async def test_register_weak_password(self, test_client):
        client, _ = test_client
        resp = await client.post(
            "/graphql",
            json=gql(REGISTER_MUTATION, {"email": "weak@example.com", "password": "short"}),
        )
        data = resp.json()["data"]["register"]
        assert data["success"] is False

    async def test_register_invalid_email(self, test_client):
        client, _ = test_client
        resp = await client.post(
            "/graphql",
            json=gql(REGISTER_MUTATION, {"email": "not-an-email", "password": "SecurePass1"}),
        )
        data = resp.json()["data"]["register"]
        assert data["success"] is False


@skip_no_services
class TestLogin:
    async def _register_and_login(self, client, email: str, password: str = "SecurePass1"):
        await client.post(
            "/graphql",
            json=gql(REGISTER_MUTATION, {"email": email, "password": password}),
        )
        resp = await client.post(
            "/graphql", json=gql(LOGIN_MUTATION, {"email": email, "password": password})
        )
        return resp.json()["data"]["login"]

    async def test_login_success(self, test_client):
        client, _ = test_client
        email = f"login-{uuid.uuid4().hex[:8]}@example.com"
        payload = await self._register_and_login(client, email)
        assert payload["accessToken"]
        assert payload["refreshToken"]
        assert payload["sessionId"]
        assert payload["tokenType"] == "Bearer"

    async def test_login_wrong_password(self, test_client):
        client, _ = test_client
        email = f"wrong-{uuid.uuid4().hex[:8]}@example.com"
        await client.post(
            "/graphql",
            json=gql(REGISTER_MUTATION, {"email": email, "password": "SecurePass1"}),
        )
        resp = await client.post(
            "/graphql", json=gql(LOGIN_MUTATION, {"email": email, "password": "WrongPass1"})
        )
        body = resp.json()
        assert "errors" in body

    async def test_login_unknown_user(self, test_client):
        client, _ = test_client
        resp = await client.post(
            "/graphql",
            json=gql(LOGIN_MUTATION, {"email": "nobody@example.com", "password": "SecurePass1"}),
        )
        body = resp.json()
        assert "errors" in body


@skip_no_services
class TestMeQuery:
    async def _register_login(self, client, email: str):
        await client.post(
            "/graphql",
            json=gql(REGISTER_MUTATION, {"email": email, "password": "SecurePass1"}),
        )
        resp = await client.post(
            "/graphql",
            json=gql(LOGIN_MUTATION, {"email": email, "password": "SecurePass1"}),
        )
        return resp.json()["data"]["login"]

    async def test_me_authenticated(self, test_client):
        client, _ = test_client
        email = f"me-{uuid.uuid4().hex[:8]}@example.com"
        login_data = await self._register_login(client, email)
        access_token = login_data["accessToken"]

        resp = await client.post(
            "/graphql",
            json=gql(ME_QUERY),
            headers={"Authorization": f"Bearer {access_token}"},
        )
        data = resp.json()["data"]["me"]
        assert data is not None
        assert data["email"] == email
        assert data["isActive"] is True

    async def test_me_no_token(self, test_client):
        client, _ = test_client
        resp = await client.post("/graphql", json=gql(ME_QUERY))
        data = resp.json()["data"]["me"]
        assert data is None

    async def test_me_invalid_token(self, test_client):
        client, _ = test_client
        resp = await client.post(
            "/graphql",
            json=gql(ME_QUERY),
            headers={"Authorization": "Bearer not.a.real.jwt"},
        )
        data = resp.json()["data"]["me"]
        assert data is None

    async def test_me_revoked_session(self, test_client):
        client, _ = test_client
        email = f"revoke-{uuid.uuid4().hex[:8]}@example.com"
        login_data = await self._register_login(client, email)
        access_token = login_data["accessToken"]
        session_id = login_data["sessionId"]

        # Revoke the session — auth header required (revokeSession requires Bearer token)
        await client.post(
            "/graphql",
            json=gql(REVOKE_MUTATION, {"sessionId": session_id}),
            headers={"Authorization": f"Bearer {access_token}"},
        )

        # me query should now return null (jti no longer in Redis)
        resp = await client.post(
            "/graphql",
            json=gql(ME_QUERY),
            headers={"Authorization": f"Bearer {access_token}"},
        )
        data = resp.json()["data"]["me"]
        assert data is None


@skip_no_services
class TestRefreshToken:
    async def test_refresh_rotation(self, test_client):
        client, _ = test_client
        email = f"refresh-{uuid.uuid4().hex[:8]}@example.com"
        await client.post(
            "/graphql",
            json=gql(REGISTER_MUTATION, {"email": email, "password": "SecurePass1"}),
        )
        login_resp = await client.post(
            "/graphql", json=gql(LOGIN_MUTATION, {"email": email, "password": "SecurePass1"})
        )
        old_refresh = login_resp.json()["data"]["login"]["refreshToken"]

        # Refresh — get new tokens
        refresh_resp = await client.post(
            "/graphql", json=gql(REFRESH_MUTATION, {"token": old_refresh})
        )
        new_data = refresh_resp.json()["data"]["refreshToken"]
        assert new_data["accessToken"]
        new_refresh = new_data["refreshToken"]

        # Old refresh token should now be rejected
        rejected_resp = await client.post(
            "/graphql", json=gql(REFRESH_MUTATION, {"token": old_refresh})
        )
        assert "errors" in rejected_resp.json()

        # New refresh token must work
        second_refresh_resp = await client.post(
            "/graphql", json=gql(REFRESH_MUTATION, {"token": new_refresh})
        )
        assert second_refresh_resp.json()["data"]["refreshToken"]["accessToken"]

    async def test_refresh_invalid_token(self, test_client):
        client, _ = test_client
        resp = await client.post(
            "/graphql", json=gql(REFRESH_MUTATION, {"token": "nonexistent-token"})
        )
        assert "errors" in resp.json()


@skip_no_services
class TestPasswordReset:
    async def test_request_reset_unknown_email(self, test_client):
        # Unknown email returns success=True to prevent email enumeration.
        client, _ = test_client
        resp = await client.post(
            "/graphql",
            json=gql(REQUEST_RESET_MUTATION, {"email": "nobody-reset@example.com"}),
        )
        data = resp.json()["data"]["requestPasswordReset"]
        assert data["success"] is True

    async def test_request_reset_success_token_in_db(self, test_client):
        client, container = test_client
        email = f"reset-{uuid.uuid4().hex[:8]}@example.com"
        await client.post(
            "/graphql",
            json=gql(REGISTER_MUTATION, {"email": email, "password": "SecurePass1"}),
        )
        resp = await client.post(
            "/graphql", json=gql(REQUEST_RESET_MUTATION, {"email": email})
        )
        data = resp.json()["data"]["requestPasswordReset"]
        assert data["success"] is True

    async def test_full_password_reset_flow(self, test_client, test_session_factory):
        """register → request_reset → retrieve raw token from mock email → reset → login."""
        client, container = test_client
        email = f"fullreset-{uuid.uuid4().hex[:8]}@example.com"
        old_pass = "OldPass123"
        new_pass = "NewPass456"

        # Register
        await client.post(
            "/graphql", json=gql(REGISTER_MUTATION, {"email": email, "password": old_pass})
        )

        # Request reset — raw token is captured by MockEmailService
        await client.post(
            "/graphql", json=gql(REQUEST_RESET_MUTATION, {"email": email})
        )

        # Retrieve the raw token from the mock email service (the DB stores its hash)
        assert container.email_service.sent_emails, "Expected a reset email to be sent"
        raw_token = container.email_service.sent_emails[-1][1]

        # Reset password
        resp = await client.post(
            "/graphql",
            json=gql(RESET_PASSWORD_MUTATION, {"token": raw_token, "newPassword": new_pass}),
        )
        data = resp.json()["data"]["resetPassword"]
        assert data["success"] is True

        # Old password should fail
        old_login_resp = await client.post(
            "/graphql", json=gql(LOGIN_MUTATION, {"email": email, "password": old_pass})
        )
        assert "errors" in old_login_resp.json()

        # New password must work
        new_login_resp = await client.post(
            "/graphql", json=gql(LOGIN_MUTATION, {"email": email, "password": new_pass})
        )
        assert new_login_resp.json()["data"]["login"]["accessToken"]

    async def test_reset_token_single_use(self, test_client, test_session_factory):
        """Consuming a reset token twice raises TokenAlreadyUsedError."""
        client, container = test_client
        email = f"singleuse-{uuid.uuid4().hex[:8]}@example.com"

        await client.post(
            "/graphql", json=gql(REGISTER_MUTATION, {"email": email, "password": "OldPass123"})
        )
        await client.post(
            "/graphql", json=gql(REQUEST_RESET_MUTATION, {"email": email})
        )

        # Retrieve the raw token from the mock email service (the DB stores its hash)
        assert container.email_service.sent_emails, "Expected a reset email to be sent"
        raw_token = container.email_service.sent_emails[-1][1]

        # First use — success
        first = await client.post(
            "/graphql",
            json=gql(RESET_PASSWORD_MUTATION, {"token": raw_token, "newPassword": "NewPass456"}),
        )
        assert first.json()["data"]["resetPassword"]["success"] is True

        # Second use — must fail
        second = await client.post(
            "/graphql",
            json=gql(RESET_PASSWORD_MUTATION, {"token": raw_token, "newPassword": "AnotherPass1"}),
        )
        data = second.json()["data"]["resetPassword"]
        assert data["success"] is False


# ---------------------------------------------------------------------------
# Idempotency
# ---------------------------------------------------------------------------


@skip_no_services
class TestIdempotency:
    """Integration tests for IdempotencyExtension — login and requestPasswordReset."""

    async def _register(self, client, email: str, password: str = "SecurePass1") -> None:
        await client.post(
            "/graphql",
            json=gql(REGISTER_MUTATION, {"email": email, "password": password}),
        )

    async def test_login_same_key_returns_same_tokens(self, test_client):
        """Two login calls with the same Idempotency-Key must return identical tokens."""
        client, _ = test_client
        email = f"idem-login-{uuid.uuid4().hex[:8]}@example.com"
        await self._register(client, email)

        headers = {"Idempotency-Key": f"login-key-{uuid.uuid4().hex}"}
        payload = gql(LOGIN_MUTATION, {"email": email, "password": "SecurePass1"})

        resp1 = await client.post("/graphql", json=payload, headers=headers)
        resp2 = await client.post("/graphql", json=payload, headers=headers)

        data1 = resp1.json()["data"]["login"]
        data2 = resp2.json()["data"]["login"]

        assert data1["accessToken"] == data2["accessToken"]
        assert data1["refreshToken"] == data2["refreshToken"]
        assert data1["sessionId"] == data2["sessionId"]

    async def test_login_same_key_creates_only_one_session(self, test_client):
        """Repeated login with same key should not create extra Redis sessions."""
        client, container = test_client
        email = f"idem-session-{uuid.uuid4().hex[:8]}@example.com"
        await self._register(client, email)

        headers = {"Idempotency-Key": f"login-key-{uuid.uuid4().hex}"}
        payload = gql(LOGIN_MUTATION, {"email": email, "password": "SecurePass1"})

        resp1 = await client.post("/graphql", json=payload, headers=headers)
        session_id_1 = resp1.json()["data"]["login"]["sessionId"]

        resp2 = await client.post("/graphql", json=payload, headers=headers)
        session_id_2 = resp2.json()["data"]["login"]["sessionId"]

        # Both calls return the same session — only one was created
        assert session_id_1 == session_id_2

    async def test_login_same_key_different_body_conflict(self, test_client):
        """Same Idempotency-Key but different request body must return IDEMPOTENCY_CONFLICT."""
        client, _ = test_client
        email1 = f"idem-conf1-{uuid.uuid4().hex[:8]}@example.com"
        email2 = f"idem-conf2-{uuid.uuid4().hex[:8]}@example.com"
        await self._register(client, email1)
        await self._register(client, email2)

        idempotency_key = f"conflict-key-{uuid.uuid4().hex}"
        headers = {"Idempotency-Key": idempotency_key}

        # First call — email1
        await client.post(
            "/graphql",
            json=gql(LOGIN_MUTATION, {"email": email1, "password": "SecurePass1"}),
            headers=headers,
        )

        # Second call — different email (different body) with same key
        resp2 = await client.post(
            "/graphql",
            json=gql(LOGIN_MUTATION, {"email": email2, "password": "SecurePass1"}),
            headers=headers,
        )
        body2 = resp2.json()
        assert "errors" in body2
        error_codes = [
            e.get("extensions", {}).get("code") for e in body2["errors"]
        ]
        assert "IDEMPOTENCY_CONFLICT" in error_codes

    async def test_login_without_key_executes_normally(self, test_client):
        """Absence of Idempotency-Key header must not break normal execution."""
        client, _ = test_client
        email = f"idem-nokey-{uuid.uuid4().hex[:8]}@example.com"
        await self._register(client, email)

        resp = await client.post(
            "/graphql",
            json=gql(LOGIN_MUTATION, {"email": email, "password": "SecurePass1"}),
        )
        assert resp.json()["data"]["login"]["accessToken"]

    async def test_request_password_reset_same_key_returns_same_response(self, test_client):
        """Repeated requestPasswordReset with same key returns the same response."""
        client, container = test_client
        email = f"idem-reset-{uuid.uuid4().hex[:8]}@example.com"
        await self._register(client, email)

        headers = {"Idempotency-Key": f"reset-key-{uuid.uuid4().hex}"}
        payload = gql(REQUEST_RESET_MUTATION, {"email": email})

        resp1 = await client.post("/graphql", json=payload, headers=headers)
        email_count_after_first = len(container.email_service.sent_emails)

        resp2 = await client.post("/graphql", json=payload, headers=headers)
        email_count_after_second = len(container.email_service.sent_emails)

        # Only one email dispatched — second call served from cache
        assert email_count_after_first == email_count_after_second

        data1 = resp1.json()["data"]["requestPasswordReset"]
        data2 = resp2.json()["data"]["requestPasswordReset"]
        assert data1["success"] == data2["success"]

    async def test_request_password_reset_same_key_different_body_conflict(self, test_client):
        """Same Idempotency-Key with different email must return IDEMPOTENCY_CONFLICT."""
        client, _ = test_client
        email1 = f"idem-rr1-{uuid.uuid4().hex[:8]}@example.com"
        email2 = f"idem-rr2-{uuid.uuid4().hex[:8]}@example.com"
        await self._register(client, email1)
        await self._register(client, email2)

        idempotency_key = f"reset-conflict-{uuid.uuid4().hex}"
        headers = {"Idempotency-Key": idempotency_key}

        # First call with email1
        await client.post(
            "/graphql",
            json=gql(REQUEST_RESET_MUTATION, {"email": email1}),
            headers=headers,
        )

        # Second call with email2 (different body)
        resp2 = await client.post(
            "/graphql",
            json=gql(REQUEST_RESET_MUTATION, {"email": email2}),
            headers=headers,
        )
        body2 = resp2.json()
        assert "errors" in body2
        error_codes = [
            e.get("extensions", {}).get("code") for e in body2["errors"]
        ]
        assert "IDEMPOTENCY_CONFLICT" in error_codes

    async def test_non_idempotent_mutation_ignores_key(self, test_client):
        """Idempotency-Key header on register (non-idempotent op) must be ignored."""
        client, _ = test_client
        email1 = f"idem-reg1-{uuid.uuid4().hex[:8]}@example.com"
        email2 = f"idem-reg2-{uuid.uuid4().hex[:8]}@example.com"

        headers = {"Idempotency-Key": f"reg-key-{uuid.uuid4().hex}"}

        resp1 = await client.post(
            "/graphql",
            json=gql(REGISTER_MUTATION, {"email": email1, "password": "SecurePass1"}),
            headers=headers,
        )
        resp2 = await client.post(
            "/graphql",
            json=gql(REGISTER_MUTATION, {"email": email2, "password": "SecurePass1"}),
            headers=headers,
        )

        # Both should succeed independently — no idempotency applied
        assert resp1.json()["data"]["register"]["success"] is True
        assert resp2.json()["data"]["register"]["success"] is True

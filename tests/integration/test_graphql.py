"""Integration tests for the GraphQL API — require PostgreSQL + Redis."""
from __future__ import annotations

import os
import socket
import uuid
from contextlib import asynccontextmanager
from typing import AsyncGenerator

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import redis.asyncio as aioredis

from auth_service.infrastructure.db.models import Base

pytestmark = pytest.mark.integration

# ---------------------------------------------------------------------------
# Availability checks
# ---------------------------------------------------------------------------

_TEST_DB_URL = os.environ.get(
    "DB_TEST_URL",
    "postgresql+asyncpg://auth_user:auth_password@localhost:5432/auth_test",
)
_REDIS_URL = os.environ.get("REDIS_TEST_URL", "redis://localhost:6379/2")


def _port_open(host: str, port: int) -> bool:
    try:
        with socket.create_connection((host, port), timeout=1):
            return True
    except OSError:
        return False


_db_available = _port_open("localhost", 5432)
_redis_available = _port_open("localhost", 6379)
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
    from fastapi import FastAPI, Request
    from auth_service.container import GlobalContainer, set_global_container
    from auth_service.presentation.graphql.schema import create_graphql_router

    async def get_context(request: Request) -> AsyncGenerator[dict, None]:
        async with container.request_scope() as scope:
            yield {"request": request, "container": scope}

    container = GlobalContainer(
        redis_client=redis_client,
        session_factory=test_session_factory,
    )
    # Override JWT secret for predictable tests
    import os
    os.environ.setdefault("JWT_SECRET", "test-secret-key")

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
        assert "already exists" in data["message"].lower()

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
        client, _ = test_client
        resp = await client.post(
            "/graphql",
            json=gql(REQUEST_RESET_MUTATION, {"email": "nobody-reset@example.com"}),
        )
        data = resp.json()["data"]["requestPasswordReset"]
        assert data["success"] is False

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
        """register → request_reset → read token from DB → reset → login with new password."""
        client, container = test_client
        email = f"fullreset-{uuid.uuid4().hex[:8]}@example.com"
        old_pass = "OldPass123"
        new_pass = "NewPass456"

        # Register
        await client.post(
            "/graphql", json=gql(REGISTER_MUTATION, {"email": email, "password": old_pass})
        )

        # Request reset
        await client.post(
            "/graphql", json=gql(REQUEST_RESET_MUTATION, {"email": email})
        )

        # Read token directly from DB
        from sqlalchemy import select, text
        from auth_service.infrastructure.db.models import PasswordResetTokenModel, UserModel
        from auth_service.domain.value_objects.email import Email

        async with test_session_factory() as session:
            user_result = await session.execute(
                select(UserModel).where(UserModel.email == email)
            )
            user_model = user_result.scalar_one()
            token_result = await session.execute(
                select(PasswordResetTokenModel).where(
                    PasswordResetTokenModel.user_id == user_model.id
                )
            )
            token_model = token_result.scalar_one()
            raw_token = token_model.token

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
        client, _ = test_client
        email = f"singleuse-{uuid.uuid4().hex[:8]}@example.com"

        await client.post(
            "/graphql", json=gql(REGISTER_MUTATION, {"email": email, "password": "OldPass123"})
        )
        await client.post(
            "/graphql", json=gql(REQUEST_RESET_MUTATION, {"email": email})
        )

        from sqlalchemy import select
        from auth_service.infrastructure.db.models import PasswordResetTokenModel, UserModel

        async with test_session_factory() as session:
            user_result = await session.execute(
                select(UserModel).where(UserModel.email == email)
            )
            user_model = user_result.scalar_one()
            token_result = await session.execute(
                select(PasswordResetTokenModel).where(
                    PasswordResetTokenModel.user_id == user_model.id
                )
            )
            raw_token = token_result.scalar_one().token

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

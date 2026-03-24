import uuid
from datetime import datetime, timezone

import pytest

from auth_service.application.commands.authenticate_user import AuthenticateUserHandler
from auth_service.application.dto import AuthenticateUserCommand
from auth_service.domain.entities.user import User
from auth_service.domain.exceptions import InvalidCredentialsError
from auth_service.domain.value_objects.email import Email
from auth_service.domain.value_objects.hashed_password import HashedPassword
from tests.unit.application.fakes import (
    FakePasswordHasher,
    FakeTokenService,
    FakeTokenStore,
    FakeUserRepository,
)


def make_user(email: str, password: str) -> User:
    return User(
        id=uuid.uuid4(),
        email=Email(email),
        hashed_password=HashedPassword(f"hashed:{password}"),
        is_active=True,
        created_at=datetime.now(timezone.utc),
    )


@pytest.mark.asyncio
async def test_authenticate_user_success():
    repo = FakeUserRepository()
    user = make_user("alice@example.com", "mypassword1")
    await repo.save(user)

    hasher = FakePasswordHasher()
    token_svc = FakeTokenService()
    token_store = FakeTokenStore()

    handler = AuthenticateUserHandler(repo, hasher, token_svc, token_store)
    result = await handler.handle(
        AuthenticateUserCommand(email="alice@example.com", password="mypassword1")
    )

    assert result.access_token.startswith("access:")
    assert result.refresh_token.startswith("refresh:")
    assert result.session_id is not None
    assert token_store.sessions  # session was created


@pytest.mark.asyncio
async def test_authenticate_user_wrong_password():
    repo = FakeUserRepository()
    user = make_user("alice@example.com", "mypassword1")
    await repo.save(user)

    hasher = FakePasswordHasher()
    token_svc = FakeTokenService()
    token_store = FakeTokenStore()

    handler = AuthenticateUserHandler(repo, hasher, token_svc, token_store)

    with pytest.raises(InvalidCredentialsError):
        await handler.handle(
            AuthenticateUserCommand(email="alice@example.com", password="wrongpassword1")
        )


@pytest.mark.asyncio
async def test_authenticate_user_not_found():
    repo = FakeUserRepository()
    hasher = FakePasswordHasher()
    token_svc = FakeTokenService()
    token_store = FakeTokenStore()

    handler = AuthenticateUserHandler(repo, hasher, token_svc, token_store)

    with pytest.raises(InvalidCredentialsError):
        await handler.handle(
            AuthenticateUserCommand(email="nobody@example.com", password="mypassword1")
        )


@pytest.mark.asyncio
async def test_authenticate_returns_session_id():
    repo = FakeUserRepository()
    user = make_user("alice@example.com", "mypassword1")
    await repo.save(user)

    hasher = FakePasswordHasher()
    token_svc = FakeTokenService()
    token_store = FakeTokenStore()

    handler = AuthenticateUserHandler(repo, hasher, token_svc, token_store)
    result = await handler.handle(
        AuthenticateUserCommand(email="alice@example.com", password="mypassword1")
    )

    assert result.session_id is not None
    session = await token_store.get_session(result.session_id)
    assert session is not None
    assert session["user_id"] == user.id

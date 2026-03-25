import uuid
from datetime import datetime, timezone

import pytest

from auth_service.application.commands.authenticate_user import AuthenticateUserHandler
from auth_service.application.commands.refresh_token import RefreshTokenHandler
from auth_service.application.commands.revoke_session import RevokeSessionHandler
from auth_service.application.dto import (
    AuthenticateUserCommand,
    RefreshTokenCommand,
    RevokeSessionCommand,
)
from auth_service.domain.entities.user import User
from auth_service.domain.exceptions import InvalidTokenError
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


async def login(email: str, password: str, repo, hasher, token_svc, token_store):
    handler = AuthenticateUserHandler(repo, hasher, token_svc, token_store)
    return await handler.handle(AuthenticateUserCommand(email=email, password=password))


@pytest.mark.asyncio
async def test_refresh_token_success():
    repo = FakeUserRepository()
    user = make_user("alice@example.com", "mypassword1")
    await repo.save(user)

    hasher = FakePasswordHasher()
    token_svc = FakeTokenService()
    token_store = FakeTokenStore()

    first_pair = await login("alice@example.com", "mypassword1", repo, hasher, token_svc, token_store)

    old_jti = first_pair.access_token.split(":")[-1]

    handler = RefreshTokenHandler(token_svc, token_store)
    new_pair = await handler.handle(RefreshTokenCommand(refresh_token=first_pair.refresh_token))

    assert new_pair.access_token != first_pair.access_token
    assert new_pair.refresh_token != first_pair.refresh_token
    assert new_pair.session_id == first_pair.session_id
    # Old access JTI must be invalidated after rotation
    assert not await token_store.is_access_jti_valid(old_jti)


@pytest.mark.asyncio
async def test_refresh_token_invalid():
    token_svc = FakeTokenService()
    token_store = FakeTokenStore()

    handler = RefreshTokenHandler(token_svc, token_store)

    with pytest.raises(InvalidTokenError):
        await handler.handle(RefreshTokenCommand(refresh_token="invalid-token"))


@pytest.mark.asyncio
async def test_refresh_token_rotation_old_token_rejected():
    repo = FakeUserRepository()
    user = make_user("alice@example.com", "mypassword1")
    await repo.save(user)

    hasher = FakePasswordHasher()
    token_svc = FakeTokenService()
    token_store = FakeTokenStore()

    first_pair = await login("alice@example.com", "mypassword1", repo, hasher, token_svc, token_store)
    old_refresh = first_pair.refresh_token

    handler = RefreshTokenHandler(token_svc, token_store)
    await handler.handle(RefreshTokenCommand(refresh_token=old_refresh))

    # Old refresh token should now be invalid
    with pytest.raises(InvalidTokenError):
        await handler.handle(RefreshTokenCommand(refresh_token=old_refresh))


@pytest.mark.asyncio
async def test_revoke_session_success():
    repo = FakeUserRepository()
    user = make_user("alice@example.com", "mypassword1")
    await repo.save(user)

    hasher = FakePasswordHasher()
    token_svc = FakeTokenService()
    token_store = FakeTokenStore()

    pair = await login("alice@example.com", "mypassword1", repo, hasher, token_svc, token_store)

    handler = RevokeSessionHandler(token_store)
    await handler.handle(RevokeSessionCommand(session_id=pair.session_id))

    session = await token_store.get_session(pair.session_id)
    assert session is None


@pytest.mark.asyncio
async def test_revoke_session_already_revoked():
    token_store = FakeTokenStore()
    handler = RevokeSessionHandler(token_store)

    # Revoking a non-existent session should not raise
    await handler.handle(RevokeSessionCommand(session_id=uuid.uuid4()))

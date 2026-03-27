import hashlib
import uuid
from datetime import datetime, timedelta, timezone

import pytest

from auth_service.application.commands.request_password_reset import RequestPasswordResetHandler
from auth_service.application.commands.reset_password import ResetPasswordHandler
from auth_service.application.dto import RequestPasswordResetCommand, ResetPasswordCommand
from auth_service.domain.entities.password_reset_token import PasswordResetToken
from auth_service.domain.entities.user import User
from auth_service.domain.exceptions import (
    TokenExpiredError,
    TokenNotFoundError,
    WeakPasswordError,
)
from auth_service.domain.value_objects.email import Email
from auth_service.domain.value_objects.hashed_password import HashedPassword
from auth_service.domain.value_objects.reset_token import ResetToken
from tests.unit.application.fakes import (
    FakeEmailService,
    FakePasswordHasher,
    FakeResetTokenRepository,
    FakeTokenStore,
    FakeUserRepository,
)


def make_user(email: str) -> User:
    return User(
        id=uuid.uuid4(),
        email=Email(email),
        hashed_password=HashedPassword("hashed:oldpassword1"),
        is_active=True,
        created_at=datetime.now(timezone.utc),
    )


def _tok_hash(raw: str) -> str:
    """Return the SHA-256 hex digest of raw — matches the hashing done by the handlers."""
    return hashlib.sha256(raw.encode()).hexdigest()


def make_expired_token(user_id: uuid.UUID) -> PasswordResetToken:
    return PasswordResetToken(
        id=uuid.uuid4(),
        user_id=user_id,
        token=ResetToken(value=_tok_hash("expired-token-value")),
        expires_at=datetime.now(timezone.utc) - timedelta(minutes=1),
        used=False,
    )


def make_valid_token(user_id: uuid.UUID) -> PasswordResetToken:
    return PasswordResetToken(
        id=uuid.uuid4(),
        user_id=user_id,
        token=ResetToken(value=_tok_hash("valid-token-value")),
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=15),
        used=False,
    )


# ---- RequestPasswordReset tests ----

@pytest.mark.asyncio
async def test_request_password_reset_success():
    repo = FakeUserRepository()
    user = make_user("alice@example.com")
    await repo.save(user)

    token_repo = FakeResetTokenRepository()
    email_svc = FakeEmailService()

    handler = RequestPasswordResetHandler(repo, token_repo, email_svc)
    await handler.handle(RequestPasswordResetCommand(email="alice@example.com"))

    assert len(token_repo.tokens) == 1
    assert len(email_svc.sent_emails) == 1
    assert email_svc.sent_emails[0][0] == "alice@example.com"


@pytest.mark.asyncio
async def test_request_password_reset_unknown_email():
    # Unknown email should complete silently (no exception) to prevent email enumeration.
    repo = FakeUserRepository()
    token_repo = FakeResetTokenRepository()
    email_svc = FakeEmailService()

    handler = RequestPasswordResetHandler(repo, token_repo, email_svc)
    await handler.handle(RequestPasswordResetCommand(email="nobody@example.com"))

    assert len(email_svc.sent_emails) == 0
    assert len(token_repo.tokens) == 0


@pytest.mark.asyncio
async def test_request_password_reset_replaces_previous_token():
    repo = FakeUserRepository()
    user = make_user("alice@example.com")
    await repo.save(user)

    token_repo = FakeResetTokenRepository()
    email_svc = FakeEmailService()

    handler = RequestPasswordResetHandler(repo, token_repo, email_svc)

    await handler.handle(RequestPasswordResetCommand(email="alice@example.com"))
    first_token_value = email_svc.sent_emails[0][1]

    await handler.handle(RequestPasswordResetCommand(email="alice@example.com"))

    # Only one token should remain
    assert len(token_repo.tokens) == 1
    # The remaining token should be the new (second) one, not the first
    second_token_value = email_svc.sent_emails[1][1]
    assert second_token_value != first_token_value


# ---- ResetPassword tests ----

@pytest.mark.asyncio
async def test_reset_password_success():
    repo = FakeUserRepository()
    user = make_user("alice@example.com")
    await repo.save(user)

    token_repo = FakeResetTokenRepository()
    valid_token = make_valid_token(user.id)
    await token_repo.save(valid_token)

    hasher = FakePasswordHasher()
    token_store = FakeTokenStore()

    handler = ResetPasswordHandler(token_repo, repo, hasher, token_store)
    await handler.handle(ResetPasswordCommand(token="valid-token-value", new_password="newpass1"))

    # Password should be updated
    updated_user = await repo.find_by_id(user.id)
    assert updated_user.hashed_password.value == "hashed:newpass1"

    # Token should be marked as used (stored under its SHA-256 hash)
    saved_token = await token_repo.find_by_token(_tok_hash("valid-token-value"))
    assert saved_token.used is True


@pytest.mark.asyncio
async def test_reset_password_expired_token():
    repo = FakeUserRepository()
    user = make_user("alice@example.com")
    await repo.save(user)

    token_repo = FakeResetTokenRepository()
    expired_token = make_expired_token(user.id)
    await token_repo.save(expired_token)

    hasher = FakePasswordHasher()
    token_store = FakeTokenStore()

    handler = ResetPasswordHandler(token_repo, repo, hasher, token_store)

    with pytest.raises(TokenExpiredError):
        await handler.handle(ResetPasswordCommand(token="expired-token-value", new_password="newpass1"))


@pytest.mark.asyncio
async def test_reset_password_token_not_found():
    repo = FakeUserRepository()
    token_repo = FakeResetTokenRepository()
    hasher = FakePasswordHasher()
    token_store = FakeTokenStore()

    handler = ResetPasswordHandler(token_repo, repo, hasher, token_store)

    with pytest.raises(TokenNotFoundError):
        await handler.handle(ResetPasswordCommand(token="nonexistent", new_password="newpass1"))


@pytest.mark.asyncio
async def test_reset_password_revokes_all_sessions():
    repo = FakeUserRepository()
    user = make_user("alice@example.com")
    await repo.save(user)

    token_repo = FakeResetTokenRepository()
    valid_token = make_valid_token(user.id)
    await token_repo.save(valid_token)

    hasher = FakePasswordHasher()
    token_store = FakeTokenStore()

    # Pre-populate a session
    import uuid as _uuid
    session_id = _uuid.uuid4()
    token_store.sessions[session_id] = {"user_id": user.id, "jti": "somejti", "refresh": "somerefresh"}
    token_store.user_sessions.setdefault(user.id, set()).add(session_id)

    handler = ResetPasswordHandler(token_repo, repo, hasher, token_store)
    await handler.handle(ResetPasswordCommand(token="valid-token-value", new_password="newpass1"))

    # All sessions should be revoked
    session = await token_store.get_session(session_id)
    assert session is None


@pytest.mark.asyncio
async def test_reset_password_weak_new_password():
    repo = FakeUserRepository()
    user = make_user("alice@example.com")
    await repo.save(user)

    token_repo = FakeResetTokenRepository()
    valid_token = make_valid_token(user.id)
    await token_repo.save(valid_token)

    hasher = FakePasswordHasher()
    token_store = FakeTokenStore()

    handler = ResetPasswordHandler(token_repo, repo, hasher, token_store)

    with pytest.raises(WeakPasswordError):
        await handler.handle(ResetPasswordCommand(token="valid-token-value", new_password="short"))

"""Unit tests for audit logging in the remaining command handlers (Task 7)."""
import uuid
from datetime import datetime, timezone

import pytest

from auth_service.application.commands.refresh_token import RefreshTokenHandler
from auth_service.application.commands.request_password_reset import RequestPasswordResetHandler
from auth_service.application.commands.reset_password import ResetPasswordHandler
from auth_service.application.commands.revoke_session import RevokeSessionHandler
from auth_service.application.dto import (
    RefreshTokenCommand,
    RequestPasswordResetCommand,
    ResetPasswordCommand,
    RevokeSessionCommand,
)
from auth_service.domain.entities.password_reset_token import PasswordResetToken
from auth_service.domain.entities.user import User
from auth_service.domain.value_objects.auth_event_type import AuthEventType
from auth_service.domain.value_objects.email import Email
from auth_service.domain.value_objects.hashed_password import HashedPassword
from auth_service.domain.value_objects.reset_token import ResetToken
from tests.unit.application.fakes import (
    FailingAuditLogPort,
    FakeAuditLogPort,
    FakeEmailService,
    FakePasswordHasher,
    FakeResetTokenRepository,
    FakeTokenService,
    FakeTokenStore,
    FakeUserRepository,
)

import hashlib
from datetime import timedelta


def make_user(email: str) -> User:
    return User(
        id=uuid.uuid4(),
        email=Email(email),
        hashed_password=HashedPassword("hashed:pass1"),
        is_active=True,
        created_at=datetime.now(timezone.utc),
    )


def make_valid_token(user_id: uuid.UUID) -> PasswordResetToken:
    token_hash = hashlib.sha256(b"valid-token-value").hexdigest()
    return PasswordResetToken(
        id=uuid.uuid4(),
        user_id=user_id,
        token=ResetToken(value=token_hash),
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=15),
        used=False,
    )


# ---------------------------------------------------------------------------
# RevokeSessionHandler
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_revoke_session_records_session_revoked():
    token_store = FakeTokenStore()
    session_id = uuid.uuid4()
    user_id = uuid.uuid4()
    token_store.sessions[session_id] = {
        "user_id": user_id,
        "jti": "some-jti",
        "refresh": "some-refresh",
    }
    token_store.user_sessions[user_id] = {session_id}

    audit = FakeAuditLogPort()
    handler = RevokeSessionHandler(token_store, audit)
    await handler.handle(RevokeSessionCommand(session_id=session_id, ip_address="1.2.3.4"))

    assert len(audit.recorded) == 1
    event = audit.recorded[0]
    assert event.event_type == AuthEventType.SESSION_REVOKED
    assert event.session_id == session_id
    assert event.user_id == user_id
    assert event.ip_address == "1.2.3.4"
    assert event.metadata == {"reason": "user_logout"}


@pytest.mark.asyncio
async def test_revoke_session_audit_failure_does_not_propagate():
    token_store = FakeTokenStore()
    session_id = uuid.uuid4()
    token_store.sessions[session_id] = {"user_id": uuid.uuid4(), "jti": "j", "refresh": "r"}

    audit = FailingAuditLogPort()
    handler = RevokeSessionHandler(token_store, audit)
    # Should not raise even though audit log always raises
    await handler.handle(RevokeSessionCommand(session_id=session_id))


# ---------------------------------------------------------------------------
# RefreshTokenHandler
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_refresh_token_records_token_refreshed():
    token_store = FakeTokenStore()
    user_id = uuid.uuid4()
    session_id = uuid.uuid4()
    refresh_token = "refresh:abc"
    token_store.sessions[session_id] = {
        "user_id": user_id,
        "jti": "old-jti",
        "refresh": refresh_token,
        "device_info": None,
    }
    token_store.refresh_tokens[refresh_token] = {
        "user_id": user_id,
        "session_id": session_id,
    }
    token_store.access_jtis["old-jti"] = session_id
    token_store.user_sessions[user_id] = {session_id}

    audit = FakeAuditLogPort()
    handler = RefreshTokenHandler(FakeTokenService(), token_store, audit)
    result = await handler.handle(RefreshTokenCommand(refresh_token=refresh_token, ip_address="5.6.7.8"))

    assert len(audit.recorded) == 1
    event = audit.recorded[0]
    assert event.event_type == AuthEventType.TOKEN_REFRESHED
    assert event.user_id == user_id
    assert event.session_id == session_id
    assert event.ip_address == "5.6.7.8"
    assert event.metadata == {}


@pytest.mark.asyncio
async def test_refresh_token_audit_failure_does_not_propagate():
    token_store = FakeTokenStore()
    user_id = uuid.uuid4()
    session_id = uuid.uuid4()
    refresh_token = "refresh:xyz"
    token_store.sessions[session_id] = {
        "user_id": user_id,
        "jti": "j",
        "refresh": refresh_token,
        "device_info": None,
    }
    token_store.refresh_tokens[refresh_token] = {
        "user_id": user_id,
        "session_id": session_id,
    }
    token_store.access_jtis["j"] = session_id

    audit = FailingAuditLogPort()
    handler = RefreshTokenHandler(FakeTokenService(), token_store, audit)
    result = await handler.handle(RefreshTokenCommand(refresh_token=refresh_token))
    # Result should still be returned despite audit failure
    assert result.access_token.startswith("access:")


# ---------------------------------------------------------------------------
# RequestPasswordResetHandler
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_request_password_reset_records_event():
    repo = FakeUserRepository()
    user = make_user("alice@example.com")
    await repo.save(user)

    token_repo = FakeResetTokenRepository()
    email_svc = FakeEmailService()
    audit = FakeAuditLogPort()
    handler = RequestPasswordResetHandler(repo, token_repo, email_svc, audit)
    await handler.handle(RequestPasswordResetCommand(email="alice@example.com", ip_address="9.9.9.9"))

    assert len(audit.recorded) == 1
    event = audit.recorded[0]
    assert event.event_type == AuthEventType.PASSWORD_RESET_REQUESTED
    assert event.user_id == user.id
    assert event.ip_address == "9.9.9.9"
    assert event.metadata == {}


@pytest.mark.asyncio
async def test_request_password_reset_no_audit_for_unknown_email():
    repo = FakeUserRepository()
    token_repo = FakeResetTokenRepository()
    email_svc = FakeEmailService()
    audit = FakeAuditLogPort()
    handler = RequestPasswordResetHandler(repo, token_repo, email_svc, audit)
    # Unknown email — should complete silently, no audit event
    await handler.handle(RequestPasswordResetCommand(email="nobody@example.com"))
    assert len(audit.recorded) == 0


@pytest.mark.asyncio
async def test_request_password_reset_audit_failure_does_not_propagate():
    repo = FakeUserRepository()
    user = make_user("bob@example.com")
    await repo.save(user)

    token_repo = FakeResetTokenRepository()
    email_svc = FakeEmailService()
    audit = FailingAuditLogPort()
    handler = RequestPasswordResetHandler(repo, token_repo, email_svc, audit)
    # Should not raise despite audit log always raising
    await handler.handle(RequestPasswordResetCommand(email="bob@example.com"))
    # Email was still sent
    assert len(email_svc.sent_emails) == 1


# ---------------------------------------------------------------------------
# ResetPasswordHandler
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_reset_password_records_event():
    repo = FakeUserRepository()
    user = make_user("carol@example.com")
    await repo.save(user)

    token_repo = FakeResetTokenRepository()
    valid_token = make_valid_token(user.id)
    await token_repo.save(valid_token)

    hasher = FakePasswordHasher()
    token_store = FakeTokenStore()
    audit = FakeAuditLogPort()
    handler = ResetPasswordHandler(token_repo, repo, hasher, token_store, audit)
    await handler.handle(
        ResetPasswordCommand(token="valid-token-value", new_password="newpass1", ip_address="10.0.0.1")
    )

    assert len(audit.recorded) == 1
    event = audit.recorded[0]
    assert event.event_type == AuthEventType.PASSWORD_RESET_COMPLETED
    assert event.user_id == user.id
    assert event.ip_address == "10.0.0.1"
    assert event.metadata == {}


@pytest.mark.asyncio
async def test_reset_password_audit_failure_does_not_propagate():
    repo = FakeUserRepository()
    user = make_user("dave@example.com")
    await repo.save(user)

    token_repo = FakeResetTokenRepository()
    valid_token = make_valid_token(user.id)
    await token_repo.save(valid_token)

    hasher = FakePasswordHasher()
    token_store = FakeTokenStore()
    audit = FailingAuditLogPort()
    handler = ResetPasswordHandler(token_repo, repo, hasher, token_store, audit)
    # Should not raise despite audit log always raising
    await handler.handle(ResetPasswordCommand(token="valid-token-value", new_password="newpass1"))

    # Password should still be changed
    updated_user = await repo.find_by_id(user.id)
    assert updated_user.hashed_password.value == "hashed:newpass1"

import uuid
from datetime import datetime, timezone

import pytest

from auth_service.application.commands.authenticate_user import AuthenticateUserHandler
from auth_service.application.dto import AuthenticateUserCommand
from auth_service.domain.entities.user import User
from auth_service.domain.exceptions import InvalidCredentialsError
from auth_service.domain.value_objects.auth_event_type import AuthEventType
from auth_service.domain.value_objects.email import Email
from auth_service.domain.value_objects.hashed_password import HashedPassword
from tests.unit.application.fakes import (
    FailingAuditLogPort,
    FakeAuditLogPort,
    FakePasswordHasher,
    FakeTokenService,
    FakeTokenStore,
    FakeUserRepository,
)


def make_user(email: str, password: str, is_active: bool = True) -> User:
    return User(
        id=uuid.uuid4(),
        email=Email(email),
        hashed_password=HashedPassword(f"hashed:{password}"),
        is_active=is_active,
        created_at=datetime.now(timezone.utc),
    )


def make_handler(repo=None, hasher=None, token_svc=None, token_store=None, audit_log=None):
    return AuthenticateUserHandler(
        user_repo=repo or FakeUserRepository(),
        hasher=hasher or FakePasswordHasher(),
        token_service=token_svc or FakeTokenService(),
        token_store=token_store or FakeTokenStore(),
        audit_log=audit_log or FakeAuditLogPort(),
    )


@pytest.mark.asyncio
async def test_authenticate_user_success():
    repo = FakeUserRepository()
    user = make_user("alice@example.com", "mypassword1")
    await repo.save(user)

    token_store = FakeTokenStore()
    handler = make_handler(repo=repo, token_store=token_store)
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

    handler = make_handler(repo=repo)

    with pytest.raises(InvalidCredentialsError):
        await handler.handle(
            AuthenticateUserCommand(email="alice@example.com", password="wrongpassword1")
        )


@pytest.mark.asyncio
async def test_authenticate_user_not_found():
    handler = make_handler()

    with pytest.raises(InvalidCredentialsError):
        await handler.handle(
            AuthenticateUserCommand(email="nobody@example.com", password="mypassword1")
        )


@pytest.mark.asyncio
async def test_authenticate_inactive_user_raises():
    repo = FakeUserRepository()
    user = make_user("inactive@example.com", "mypassword1", is_active=False)
    await repo.save(user)

    handler = make_handler(repo=repo)

    with pytest.raises(InvalidCredentialsError):
        await handler.handle(
            AuthenticateUserCommand(email="inactive@example.com", password="mypassword1")
        )


@pytest.mark.asyncio
async def test_authenticate_returns_session_id():
    repo = FakeUserRepository()
    user = make_user("alice@example.com", "mypassword1")
    await repo.save(user)

    token_store = FakeTokenStore()
    handler = make_handler(repo=repo, token_store=token_store)
    result = await handler.handle(
        AuthenticateUserCommand(email="alice@example.com", password="mypassword1")
    )

    assert result.session_id is not None
    session = await token_store.get_session(result.session_id)
    assert session is not None
    assert session["user_id"] == user.id


# --- Audit log tests ---


@pytest.mark.asyncio
async def test_audit_login_success_recorded():
    repo = FakeUserRepository()
    user = make_user("alice@example.com", "mypassword1")
    await repo.save(user)

    audit = FakeAuditLogPort()
    handler = make_handler(repo=repo, audit_log=audit)
    result = await handler.handle(
        AuthenticateUserCommand(email="alice@example.com", password="mypassword1", ip_address="1.2.3.4")
    )

    assert len(audit.recorded) == 1
    event = audit.recorded[0]
    assert event.event_type == AuthEventType.LOGIN_SUCCESS
    assert event.user_id == user.id
    assert event.session_id == result.session_id
    assert event.ip_address == "1.2.3.4"


@pytest.mark.asyncio
async def test_audit_login_failed_invalid_password():
    repo = FakeUserRepository()
    user = make_user("alice@example.com", "mypassword1")
    await repo.save(user)

    audit = FakeAuditLogPort()
    handler = make_handler(repo=repo, audit_log=audit)

    with pytest.raises(InvalidCredentialsError):
        await handler.handle(
            AuthenticateUserCommand(email="alice@example.com", password="wrong", ip_address="1.2.3.4")
        )

    assert len(audit.recorded) == 1
    event = audit.recorded[0]
    assert event.event_type == AuthEventType.LOGIN_FAILED
    assert event.user_id == user.id
    assert event.metadata == {"reason": "invalid_password"}
    assert event.ip_address == "1.2.3.4"


@pytest.mark.asyncio
async def test_audit_login_failed_user_not_found():
    audit = FakeAuditLogPort()
    handler = make_handler(audit_log=audit)

    with pytest.raises(InvalidCredentialsError):
        await handler.handle(
            AuthenticateUserCommand(email="ghost@example.com", password="any", ip_address="5.6.7.8")
        )

    assert len(audit.recorded) == 1
    event = audit.recorded[0]
    assert event.event_type == AuthEventType.LOGIN_FAILED
    assert event.user_id is None
    assert event.metadata == {"reason": "user_not_found"}
    assert event.ip_address == "5.6.7.8"


@pytest.mark.asyncio
async def test_audit_login_failed_inactive_account():
    repo = FakeUserRepository()
    user = make_user("inactive@example.com", "mypassword1", is_active=False)
    await repo.save(user)

    audit = FakeAuditLogPort()
    handler = make_handler(repo=repo, audit_log=audit)

    with pytest.raises(InvalidCredentialsError):
        await handler.handle(
            AuthenticateUserCommand(email="inactive@example.com", password="mypassword1", ip_address="9.9.9.9")
        )

    assert len(audit.recorded) == 1
    event = audit.recorded[0]
    assert event.event_type == AuthEventType.LOGIN_FAILED
    assert event.user_id == user.id
    assert event.metadata == {"reason": "inactive_account"}
    assert event.ip_address == "9.9.9.9"


@pytest.mark.asyncio
async def test_audit_failure_does_not_propagate_on_success():
    repo = FakeUserRepository()
    user = make_user("alice@example.com", "mypassword1")
    await repo.save(user)

    audit = FailingAuditLogPort()
    handler = make_handler(repo=repo, audit_log=audit)

    # Should not raise despite audit log always raising
    result = await handler.handle(
        AuthenticateUserCommand(email="alice@example.com", password="mypassword1")
    )
    assert result.access_token.startswith("access:")


@pytest.mark.asyncio
async def test_audit_failure_does_not_propagate_on_login_failed():
    repo = FakeUserRepository()
    user = make_user("alice@example.com", "mypassword1")
    await repo.save(user)

    audit = FailingAuditLogPort()
    handler = make_handler(repo=repo, audit_log=audit)

    # The InvalidCredentialsError must still propagate, not the audit error
    with pytest.raises(InvalidCredentialsError):
        await handler.handle(
            AuthenticateUserCommand(email="alice@example.com", password="wrong")
        )

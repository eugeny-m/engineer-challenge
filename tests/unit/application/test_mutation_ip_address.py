"""Unit tests for mutation resolvers — verify IP address extraction and forwarding."""
from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

from auth_service.application.dto import (
    AuthenticateUserCommand,
    RefreshTokenCommand,
    RequestPasswordResetCommand,
    ResetPasswordCommand,
    RevokeSessionCommand,
    TokenPairDTO,
)
from auth_service.presentation.graphql.mutations import AuthMutation
from auth_service.presentation.graphql.types import (
    LoginInput,
    RefreshTokenInput,
    RequestResetInput,
    ResetPasswordInput,
    RevokeSessionInput,
)


def _make_request(ip: str | None):
    request = MagicMock()
    if ip is not None:
        request.client = MagicMock()
        request.client.host = ip
    else:
        request.client = None
    return request


def _token_pair() -> TokenPairDTO:
    return TokenPairDTO(
        access_token="access-token",
        refresh_token="refresh-token",
        session_id=uuid.uuid4(),
    )


@pytest.mark.asyncio
async def test_login_passes_ip_address():
    handler = AsyncMock(return_value=_token_pair())
    container = MagicMock()
    container.authenticate_user_handler = handler

    info = MagicMock()
    info.context = {"request": _make_request("1.2.3.4"), "container": container}

    mutation = AuthMutation()
    await mutation.login(info, LoginInput(email="a@b.com", password="Pass1234"))

    handler.handle.assert_called_once()
    cmd: AuthenticateUserCommand = handler.handle.call_args[0][0]
    assert cmd.ip_address == "1.2.3.4"
    assert cmd.email == "a@b.com"


@pytest.mark.asyncio
async def test_login_ip_none_when_no_client():
    handler = AsyncMock(return_value=_token_pair())
    container = MagicMock()
    container.authenticate_user_handler = handler

    info = MagicMock()
    info.context = {"request": _make_request(None), "container": container}

    mutation = AuthMutation()
    await mutation.login(info, LoginInput(email="a@b.com", password="Pass1234"))

    cmd: AuthenticateUserCommand = handler.handle.call_args[0][0]
    assert cmd.ip_address is None


@pytest.mark.asyncio
async def test_refresh_token_passes_ip_address():
    handler = AsyncMock(return_value=_token_pair())
    container = MagicMock()
    container.refresh_token_handler = handler

    info = MagicMock()
    info.context = {"request": _make_request("10.0.0.1"), "container": container}

    mutation = AuthMutation()
    await mutation.refresh_token(info, RefreshTokenInput(refresh_token="some-refresh"))

    handler.handle.assert_called_once()
    cmd: RefreshTokenCommand = handler.handle.call_args[0][0]
    assert cmd.ip_address == "10.0.0.1"
    assert cmd.refresh_token == "some-refresh"


@pytest.mark.asyncio
async def test_refresh_token_ip_none_when_no_client():
    handler = AsyncMock(return_value=_token_pair())
    container = MagicMock()
    container.refresh_token_handler = handler

    info = MagicMock()
    info.context = {"request": _make_request(None), "container": container}

    mutation = AuthMutation()
    await mutation.refresh_token(info, RefreshTokenInput(refresh_token="some-refresh"))

    cmd: RefreshTokenCommand = handler.handle.call_args[0][0]
    assert cmd.ip_address is None


@pytest.mark.asyncio
async def test_revoke_session_passes_ip_address():
    session_id = uuid.uuid4()
    user_id = str(uuid.uuid4())
    jti = "test-jti"
    access_token = f"access:{user_id}:{session_id}:{jti}"

    # Mock token service
    token_service = MagicMock()
    token_service.decode_access_token.return_value = {"sub": user_id, "jti": jti}

    # Mock token store
    token_store = AsyncMock()
    token_store.is_access_jti_valid.return_value = True
    token_store.get_session.return_value = {"user_id": user_id}

    # Mock revoke handler
    revoke_handler = AsyncMock(return_value=None)

    container = MagicMock()
    container.token_service = token_service
    container.token_store = token_store
    container.revoke_session_handler = revoke_handler

    request = _make_request("5.6.7.8")
    request.headers = {"Authorization": f"Bearer {access_token}"}

    info = MagicMock()
    info.context = {"request": request, "container": container}

    mutation = AuthMutation()
    result = await mutation.revoke_session(
        info, RevokeSessionInput(session_id=strawberry_id(str(session_id)))
    )

    assert result.success is True
    revoke_handler.handle.assert_called_once()
    cmd: RevokeSessionCommand = revoke_handler.handle.call_args[0][0]
    assert cmd.ip_address == "5.6.7.8"
    assert cmd.session_id == session_id


@pytest.mark.asyncio
async def test_revoke_session_ip_none_when_no_client():
    session_id = uuid.uuid4()
    user_id = str(uuid.uuid4())
    jti = "test-jti"
    access_token = f"access:{user_id}:{session_id}:{jti}"

    token_service = MagicMock()
    token_service.decode_access_token.return_value = {"sub": user_id, "jti": jti}

    token_store = AsyncMock()
    token_store.is_access_jti_valid.return_value = True
    token_store.get_session.return_value = {"user_id": user_id}

    revoke_handler = AsyncMock(return_value=None)

    container = MagicMock()
    container.token_service = token_service
    container.token_store = token_store
    container.revoke_session_handler = revoke_handler

    request = _make_request(None)
    request.headers = {"Authorization": f"Bearer {access_token}"}

    info = MagicMock()
    info.context = {"request": request, "container": container}

    mutation = AuthMutation()
    await mutation.revoke_session(
        info, RevokeSessionInput(session_id=strawberry_id(str(session_id)))
    )

    cmd: RevokeSessionCommand = revoke_handler.handle.call_args[0][0]
    assert cmd.ip_address is None


@pytest.mark.asyncio
async def test_request_password_reset_passes_ip_address():
    handler = AsyncMock(return_value=None)
    container = MagicMock()
    container.request_password_reset_handler = handler

    info = MagicMock()
    info.context = {"request": _make_request("192.168.1.1"), "container": container}

    mutation = AuthMutation()
    await mutation.request_password_reset(info, RequestResetInput(email="user@example.com"))

    handler.handle.assert_called_once()
    cmd: RequestPasswordResetCommand = handler.handle.call_args[0][0]
    assert cmd.ip_address == "192.168.1.1"
    assert cmd.email == "user@example.com"


@pytest.mark.asyncio
async def test_request_password_reset_ip_none_when_no_client():
    handler = AsyncMock(return_value=None)
    container = MagicMock()
    container.request_password_reset_handler = handler

    info = MagicMock()
    info.context = {"request": _make_request(None), "container": container}

    mutation = AuthMutation()
    await mutation.request_password_reset(info, RequestResetInput(email="user@example.com"))

    cmd: RequestPasswordResetCommand = handler.handle.call_args[0][0]
    assert cmd.ip_address is None


@pytest.mark.asyncio
async def test_reset_password_passes_ip_address():
    handler = AsyncMock(return_value=None)
    container = MagicMock()
    container.reset_password_handler = handler

    info = MagicMock()
    info.context = {"request": _make_request("172.16.0.1"), "container": container}

    mutation = AuthMutation()
    await mutation.reset_password(
        info, ResetPasswordInput(token="reset-tok", new_password="NewPass123")
    )

    handler.handle.assert_called_once()
    cmd: ResetPasswordCommand = handler.handle.call_args[0][0]
    assert cmd.ip_address == "172.16.0.1"
    assert cmd.token == "reset-tok"
    assert cmd.new_password == "NewPass123"


@pytest.mark.asyncio
async def test_reset_password_ip_none_when_no_client():
    handler = AsyncMock(return_value=None)
    container = MagicMock()
    container.reset_password_handler = handler

    info = MagicMock()
    info.context = {"request": _make_request(None), "container": container}

    mutation = AuthMutation()
    await mutation.reset_password(
        info, ResetPasswordInput(token="reset-tok", new_password="NewPass123")
    )

    cmd: ResetPasswordCommand = handler.handle.call_args[0][0]
    assert cmd.ip_address is None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

import strawberry as _strawberry


def strawberry_id(value: str) -> _strawberry.ID:
    return _strawberry.ID(value)

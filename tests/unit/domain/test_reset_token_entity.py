from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest

from auth_service.domain.entities.password_reset_token import PasswordResetToken
from auth_service.domain.exceptions import TokenAlreadyUsedError, TokenExpiredError
from auth_service.domain.value_objects.reset_token import ResetToken


def make_token(*, expires_delta: timedelta = timedelta(minutes=15), used: bool = False) -> PasswordResetToken:
    return PasswordResetToken(
        id=uuid4(),
        user_id=uuid4(),
        token=ResetToken("some-random-token-string"),
        expires_at=datetime.utcnow() + expires_delta,
        used=used,
    )


def test_consume_happy_path():
    token = make_token()
    result = token.consume()
    assert result.used is True
    assert result is token


def test_consume_expired():
    token = make_token(expires_delta=timedelta(minutes=-1))
    with pytest.raises(TokenExpiredError):
        token.consume()


def test_consume_already_used():
    token = make_token(used=True)
    with pytest.raises(TokenAlreadyUsedError):
        token.consume()


def test_consume_twice_raises_already_used():
    token = make_token()
    token.consume()
    with pytest.raises(TokenAlreadyUsedError):
        token.consume()


def test_consume_expired_and_used_raises_expired():
    # TTL check takes priority over used check
    token = make_token(expires_delta=timedelta(minutes=-1), used=True)
    with pytest.raises(TokenExpiredError):
        token.consume()

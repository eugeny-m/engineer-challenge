from datetime import datetime, timezone
from uuid import uuid4

import pytest

from auth_service.domain.entities.user import User
from auth_service.domain.value_objects.email import Email
from auth_service.domain.value_objects.hashed_password import HashedPassword


def make_user(**kwargs) -> User:
    defaults = dict(
        id=uuid4(),
        email=Email("test@example.com"),
        hashed_password=HashedPassword("$2b$12$fakehash"),
        is_active=True,
        created_at=datetime.now(timezone.utc),
    )
    defaults.update(kwargs)
    return User(**defaults)


def test_user_creation():
    user = make_user()
    assert user.email.value == "test@example.com"
    assert user.is_active is True
    assert user.hashed_password.value == "$2b$12$fakehash"


def test_change_password():
    user = make_user()
    new_hash = HashedPassword("$2b$12$newhash")
    user.change_password(new_hash)
    assert user.hashed_password.value == "$2b$12$newhash"


def test_deactivate():
    user = make_user(is_active=True)
    user.deactivate()
    assert user.is_active is False


def test_deactivate_idempotent():
    user = make_user(is_active=False)
    user.deactivate()
    assert user.is_active is False

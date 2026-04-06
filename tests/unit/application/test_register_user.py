import pytest

from auth_service.application.commands.register_user import RegisterUserHandler
from auth_service.application.dto import RegisterUserCommand
from auth_service.domain.exceptions import UserAlreadyExistsError, WeakPasswordError
from tests.unit.application.fakes import FakePasswordHasher, FakeUserRepository


@pytest.mark.asyncio
async def test_register_user_success():
    repo = FakeUserRepository()
    hasher = FakePasswordHasher()
    handler = RegisterUserHandler(repo, hasher)

    await handler.handle(RegisterUserCommand(email="alice@example.com", password="secure123"))

    assert len(repo.users) == 1
    user = list(repo.users.values())[0]
    assert user.email.value == "alice@example.com"
    assert user.hashed_password.value == "hashed:secure123"
    assert user.is_active is True


@pytest.mark.asyncio
async def test_register_user_duplicate_email():
    repo = FakeUserRepository()
    hasher = FakePasswordHasher()
    handler = RegisterUserHandler(repo, hasher)

    await handler.handle(RegisterUserCommand(email="alice@example.com", password="secure123"))

    with pytest.raises(UserAlreadyExistsError):
        await handler.handle(RegisterUserCommand(email="alice@example.com", password="secure123"))


@pytest.mark.asyncio
async def test_register_user_weak_password():
    repo = FakeUserRepository()
    hasher = FakePasswordHasher()
    handler = RegisterUserHandler(repo, hasher)

    with pytest.raises(WeakPasswordError):
        await handler.handle(RegisterUserCommand(email="alice@example.com", password="short"))


@pytest.mark.asyncio
async def test_register_normalizes_email():
    repo = FakeUserRepository()
    hasher = FakePasswordHasher()
    handler = RegisterUserHandler(repo, hasher)

    await handler.handle(RegisterUserCommand(email="Alice@EXAMPLE.COM", password="secure123"))

    user = list(repo.users.values())[0]
    assert user.email.value == "alice@example.com"

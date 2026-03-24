"""Integration tests for SQL repositories against auth_test PostgreSQL database."""
import asyncio
import os
import uuid
from datetime import datetime, timezone, timedelta

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.exc import IntegrityError

from auth_service.domain.entities.password_reset_token import PasswordResetToken
from auth_service.domain.entities.user import User
from auth_service.domain.value_objects.email import Email
from auth_service.domain.value_objects.hashed_password import HashedPassword
from auth_service.domain.value_objects.reset_token import ResetToken
from auth_service.infrastructure.db.models import Base
from auth_service.infrastructure.db.repositories.reset_token_repository import SqlResetTokenRepository
from auth_service.infrastructure.db.repositories.user_repository import SqlUserRepository

_TEST_DB_URL = os.environ.get(
    "DB_TEST_URL",
    "postgresql+asyncpg://auth_user:auth_password@localhost:5432/auth_test",
)

pytestmark = pytest.mark.integration


def _check_db_available() -> bool:
    """Return True if the test database is reachable."""
    import socket

    try:
        host = "localhost"
        port = 5432
        with socket.create_connection((host, port), timeout=1):
            return True
    except OSError:
        return False


_db_available = _check_db_available()
skip_no_db = pytest.mark.skipif(not _db_available, reason="PostgreSQL not available (no Docker in CI)")


@pytest_asyncio.fixture(scope="module")
async def test_engine():
    if not _db_available:
        pytest.skip("PostgreSQL not available (no Docker in CI)")
    engine = create_async_engine(_TEST_DB_URL, echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


@pytest_asyncio.fixture
async def session(test_engine):
    factory = async_sessionmaker(test_engine, expire_on_commit=False, class_=AsyncSession)
    async with factory() as s:
        yield s
        await s.rollback()


def make_user(email: str = "alice@example.com") -> User:
    return User(
        id=uuid.uuid4(),
        email=Email(email),
        hashed_password=HashedPassword("$2b$12$fakehash"),
        is_active=True,
        created_at=datetime.now(timezone.utc),
    )


def make_reset_token(user_id: uuid.UUID, token_str: str = "tok123") -> PasswordResetToken:
    return PasswordResetToken(
        id=uuid.uuid4(),
        user_id=user_id,
        token=ResetToken(token_str),
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=15),
        used=False,
    )


# ---------------------------------------------------------------------------
# SqlUserRepository tests
# ---------------------------------------------------------------------------

@skip_no_db
class TestSqlUserRepository:
    async def test_save_and_find_by_email(self, session):
        repo = SqlUserRepository(session)
        user = make_user("bob@example.com")
        await repo.save(user)
        found = await repo.find_by_email(Email("bob@example.com"))
        assert found is not None
        assert found.id == user.id
        assert found.email.value == "bob@example.com"
        assert found.hashed_password.value == "$2b$12$fakehash"

    async def test_find_by_email_not_found(self, session):
        repo = SqlUserRepository(session)
        result = await repo.find_by_email(Email("ghost@example.com"))
        assert result is None

    async def test_find_by_id(self, session):
        repo = SqlUserRepository(session)
        user = make_user("carol@example.com")
        await repo.save(user)
        found = await repo.find_by_id(user.id)
        assert found is not None
        assert found.id == user.id

    async def test_find_by_id_not_found(self, session):
        repo = SqlUserRepository(session)
        result = await repo.find_by_id(uuid.uuid4())
        assert result is None

    async def test_update_existing_user(self, session):
        repo = SqlUserRepository(session)
        user = make_user("dave@example.com")
        await repo.save(user)
        user.hashed_password = HashedPassword("$2b$12$newhash")
        await repo.save(user)
        found = await repo.find_by_id(user.id)
        assert found is not None
        assert found.hashed_password.value == "$2b$12$newhash"

    async def test_duplicate_email_raises(self, session):
        repo = SqlUserRepository(session)
        user1 = make_user("dup@example.com")
        user2 = make_user("dup@example.com")
        user2 = User(
            id=uuid.uuid4(),
            email=Email("dup@example.com"),
            hashed_password=HashedPassword("$2b$12$fakehash"),
            is_active=True,
            created_at=datetime.now(timezone.utc),
        )
        await repo.save(user1)
        with pytest.raises(IntegrityError):
            await repo.save(user2)


# ---------------------------------------------------------------------------
# SqlResetTokenRepository tests
# ---------------------------------------------------------------------------

@skip_no_db
class TestSqlResetTokenRepository:
    async def test_save_and_find_by_token(self, session):
        user_repo = SqlUserRepository(session)
        token_repo = SqlResetTokenRepository(session)

        user = make_user("eve@example.com")
        await user_repo.save(user)

        rt = make_reset_token(user.id, "unique-token-abc")
        await token_repo.save(rt)

        found = await token_repo.find_by_token("unique-token-abc")
        assert found is not None
        assert found.id == rt.id
        assert found.user_id == user.id
        assert found.token.value == "unique-token-abc"
        assert found.used is False

    async def test_find_by_token_not_found(self, session):
        token_repo = SqlResetTokenRepository(session)
        result = await token_repo.find_by_token("nonexistent-token")
        assert result is None

    async def test_delete_all_by_user_id(self, session):
        user_repo = SqlUserRepository(session)
        token_repo = SqlResetTokenRepository(session)

        user = make_user("frank@example.com")
        await user_repo.save(user)

        rt1 = make_reset_token(user.id, "token-to-delete-1")
        rt2 = make_reset_token(user.id, "token-to-delete-2")
        await token_repo.save(rt1)
        await token_repo.save(rt2)

        await token_repo.delete_all_by_user_id(user.id)

        assert await token_repo.find_by_token("token-to-delete-1") is None
        assert await token_repo.find_by_token("token-to-delete-2") is None

    async def test_update_token_used_status(self, session):
        user_repo = SqlUserRepository(session)
        token_repo = SqlResetTokenRepository(session)

        user = make_user("grace@example.com")
        await user_repo.save(user)

        rt = make_reset_token(user.id, "token-used-update")
        await token_repo.save(rt)

        rt.used = True
        await token_repo.save(rt)

        found = await token_repo.find_by_token("token-used-update")
        assert found is not None
        assert found.used is True

    async def test_delete_all_by_user_id_empty(self, session):
        user_repo = SqlUserRepository(session)
        token_repo = SqlResetTokenRepository(session)

        user = make_user("henry@example.com")
        await user_repo.save(user)

        # Should not raise even when no tokens exist
        await token_repo.delete_all_by_user_id(user.id)

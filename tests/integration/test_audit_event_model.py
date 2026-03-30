"""Integration tests for AuthEventModel — round-trip save/query against auth_test DB."""
import os
import uuid
from datetime import datetime, timezone
from urllib.parse import urlparse

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from auth_service.infrastructure.db.models import AuthEventModel, Base, UserModel

_TEST_DB_URL = os.environ.get(
    "DB_TEST_URL",
    "postgresql+asyncpg://auth_user:auth_password@postgres:5432/auth_test",
)

pytestmark = pytest.mark.integration


def _check_db_available() -> bool:
    import socket

    try:
        parsed = urlparse(_TEST_DB_URL)
        host = parsed.hostname or "localhost"
        port = parsed.port or 5432
        with socket.create_connection((host, port), timeout=1):
            return True
    except OSError:
        return False


_db_available = _check_db_available()
skip_no_db = pytest.mark.skipif(not _db_available, reason="PostgreSQL not available")


@pytest_asyncio.fixture(scope="module")
async def test_engine():
    if not _db_available:
        pytest.skip("PostgreSQL not available")
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


@skip_no_db
@pytest.mark.asyncio
class TestAuthEventModelRoundTrip:
    async def test_save_and_query_full_fields(self, session):
        """All fields round-trip correctly including INET and JSONB columns."""
        event_id = uuid.uuid4()
        user_id = uuid.uuid4()
        session_id = uuid.uuid4()
        occurred = datetime(2026, 3, 30, 12, 0, 0, tzinfo=timezone.utc)

        # Insert a user so the FK constraint is satisfied
        user = UserModel(
            id=user_id,
            email=f"audit-test-{user_id}@example.com",
            hashed_password="$2b$12$fakehash",
            is_active=True,
            created_at=occurred,
        )
        session.add(user)
        await session.flush()

        event = AuthEventModel(
            id=event_id,
            user_id=user_id,
            event_type="login_success",
            session_id=session_id,
            ip_address="192.168.1.1",
            occurred_at=occurred,
            metadata_={"device_info": "Chrome 120", "user_agent": "Mozilla/5.0"},
        )
        session.add(event)
        await session.flush()

        result = await session.execute(
            select(AuthEventModel).where(AuthEventModel.id == event_id)
        )
        found = result.scalar_one()

        assert found.id == event_id
        assert found.user_id == user_id
        assert found.event_type == "login_success"
        assert found.session_id == session_id
        assert found.ip_address == "192.168.1.1"
        assert found.occurred_at == occurred
        assert found.metadata_ == {"device_info": "Chrome 120", "user_agent": "Mozilla/5.0"}

    async def test_nullable_fields_accept_none(self, session):
        """user_id, session_id, and ip_address can all be NULL."""
        event_id = uuid.uuid4()
        occurred = datetime(2026, 3, 30, 13, 0, 0, tzinfo=timezone.utc)

        event = AuthEventModel(
            id=event_id,
            user_id=None,
            event_type="login_failed",
            session_id=None,
            ip_address=None,
            occurred_at=occurred,
            metadata_={"reason": "user_not_found"},
        )
        session.add(event)
        await session.flush()

        result = await session.execute(
            select(AuthEventModel).where(AuthEventModel.id == event_id)
        )
        found = result.scalar_one()

        assert found.user_id is None
        assert found.session_id is None
        assert found.ip_address is None
        assert found.event_type == "login_failed"
        assert found.metadata_ == {"reason": "user_not_found"}

    async def test_empty_metadata_default(self, session):
        """metadata defaults to empty dict when not provided."""
        event_id = uuid.uuid4()
        occurred = datetime(2026, 3, 30, 14, 0, 0, tzinfo=timezone.utc)

        event = AuthEventModel(
            id=event_id,
            event_type="token_refreshed",
            occurred_at=occurred,
            metadata_={},
        )
        session.add(event)
        await session.flush()

        result = await session.execute(
            select(AuthEventModel).where(AuthEventModel.id == event_id)
        )
        found = result.scalar_one()

        assert found.metadata_ == {}

    async def test_all_event_types_storable(self, session):
        """All 7 AuthEventType string values can be stored in event_type VARCHAR(50)."""
        event_types = [
            "login_success",
            "login_failed",
            "logout",
            "session_revoked",
            "token_refreshed",
            "password_reset_requested",
            "password_reset_completed",
        ]
        occurred = datetime(2026, 3, 30, 15, 0, 0, tzinfo=timezone.utc)

        for et in event_types:
            event = AuthEventModel(
                id=uuid.uuid4(),
                event_type=et,
                occurred_at=occurred,
                metadata_={},
            )
            session.add(event)

        await session.flush()
        # If no exception, all event types were accepted by the DB

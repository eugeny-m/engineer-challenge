"""Unit tests for AuditLogRepository with a mocked AsyncSession."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, call

import pytest

from auth_service.application.dto import AuditEventDTO
from auth_service.domain.value_objects.auth_event_type import AuthEventType
from auth_service.infrastructure.db.models import AuthEventModel
from auth_service.infrastructure.db.repositories.audit_log_repository import AuditLogRepository


def _make_dto(**overrides) -> AuditEventDTO:
    defaults = dict(
        id=uuid.uuid4(),
        event_type=AuthEventType.LOGIN_SUCCESS,
        occurred_at=datetime.now(timezone.utc),
        user_id=uuid.uuid4(),
        session_id=uuid.uuid4(),
        ip_address="192.168.1.1",
        metadata={"device_info": "Chrome"},
    )
    defaults.update(overrides)
    return AuditEventDTO(**defaults)


def _make_repo() -> tuple[AuditLogRepository, MagicMock]:
    session = MagicMock()
    session.add = MagicMock()
    session.flush = AsyncMock()
    return AuditLogRepository(session), session


class TestAuditLogRepositoryRecord:
    @pytest.mark.asyncio
    async def test_add_called_with_auth_event_model(self) -> None:
        repo, session = _make_repo()
        dto = _make_dto()
        await repo.record(dto)
        assert session.add.called
        model = session.add.call_args[0][0]
        assert isinstance(model, AuthEventModel)

    @pytest.mark.asyncio
    async def test_model_fields_match_dto(self) -> None:
        repo, session = _make_repo()
        dto = _make_dto()
        await repo.record(dto)
        model: AuthEventModel = session.add.call_args[0][0]
        assert model.id == dto.id
        assert model.user_id == dto.user_id
        assert model.event_type == dto.event_type.value
        assert model.session_id == dto.session_id
        assert model.ip_address == dto.ip_address
        assert model.occurred_at == dto.occurred_at
        assert model.metadata_ == dto.metadata

    @pytest.mark.asyncio
    async def test_flush_called_after_add(self) -> None:
        repo, session = _make_repo()
        await repo.record(_make_dto())
        session.flush.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_nullable_fields_none(self) -> None:
        repo, session = _make_repo()
        dto = _make_dto(user_id=None, session_id=None, ip_address=None)
        await repo.record(dto)
        model: AuthEventModel = session.add.call_args[0][0]
        assert model.user_id is None
        assert model.session_id is None
        assert model.ip_address is None

    @pytest.mark.asyncio
    async def test_event_type_stored_as_string_value(self) -> None:
        repo, session = _make_repo()
        dto = _make_dto(event_type=AuthEventType.LOGIN_FAILED)
        await repo.record(dto)
        model: AuthEventModel = session.add.call_args[0][0]
        assert model.event_type == "login_failed"

    @pytest.mark.asyncio
    async def test_empty_metadata_stored(self) -> None:
        repo, session = _make_repo()
        dto = _make_dto(metadata={})
        await repo.record(dto)
        model: AuthEventModel = session.add.call_args[0][0]
        assert model.metadata_ == {}

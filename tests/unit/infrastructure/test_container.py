"""Unit tests verifying AuditLogPort is wired correctly in the container."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from auth_service.application.ports.audit_log import AuditLogPort
from auth_service.container import RequestScope
from auth_service.infrastructure.db.repositories.audit_log_repository import AuditLogRepository


def _make_request_scope() -> RequestScope:
    session = MagicMock()
    session.add = MagicMock()
    session.flush = AsyncMock()

    global_container = MagicMock()
    global_container.token_service = MagicMock()
    global_container.token_store = MagicMock()
    global_container.hasher = MagicMock()
    global_container.email_service = MagicMock()
    global_container.access_token_ttl_seconds = 900
    global_container.refresh_token_ttl_seconds = 2592000
    global_container.reset_token_expire_minutes = 15

    return RequestScope(session=session, global_container=global_container)


class TestContainerAuditLogWiring:
    def test_audit_log_is_audit_log_port(self) -> None:
        scope = _make_request_scope()
        assert isinstance(scope.audit_log, AuditLogPort)

    def test_audit_log_is_audit_log_repository(self) -> None:
        scope = _make_request_scope()
        assert isinstance(scope.audit_log, AuditLogRepository)

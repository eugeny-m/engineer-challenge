import time
import uuid
from datetime import datetime, timezone
from uuid import UUID

from auth_service.application.dto import AuditEventDTO, RevokeSessionCommand
from auth_service.application.ports.audit_log import AuditLogPort
from auth_service.application.ports.token_store import TokenStore
from auth_service.domain.value_objects.auth_event_type import AuthEventType
from auth_service.infrastructure.logging import get_logger

_log = get_logger(__name__)


class RevokeSessionHandler:
    def __init__(self, token_store: TokenStore, audit_log: AuditLogPort) -> None:
        self._token_store = token_store
        self._audit_log = audit_log

    async def handle(self, command: RevokeSessionCommand) -> None:
        start = time.monotonic()
        log = _log.bind(operation="revoke_session", session_id=str(command.session_id))
        log.info("revoke_session.start")

        try:
            session_data = await self._token_store.get_session(command.session_id)
            user_id: UUID | None = None
            if session_data is not None:
                raw_uid = session_data.get("user_id")
                if raw_uid is not None:
                    user_id = UUID(str(raw_uid))

            await self._token_store.revoke_session(command.session_id)

            try:
                await self._audit_log.record(
                    AuditEventDTO(
                        id=uuid.uuid4(),
                        event_type=AuthEventType.SESSION_REVOKED,
                        occurred_at=datetime.now(timezone.utc),
                        user_id=user_id,
                        session_id=command.session_id,
                        ip_address=command.ip_address,
                        metadata={"reason": "user_logout"},
                    )
                )
            except Exception:
                pass

            duration_ms = round((time.monotonic() - start) * 1000, 2)
            log.info("revoke_session.success", duration_ms=duration_ms)
        except Exception as exc:
            duration_ms = round((time.monotonic() - start) * 1000, 2)
            log.warning("revoke_session.failure", error=str(exc), duration_ms=duration_ms)
            raise

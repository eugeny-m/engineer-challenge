from sqlalchemy.ext.asyncio import AsyncSession

from auth_service.application.dto import AuditEventDTO
from auth_service.application.ports.audit_log import AuditLogPort
from auth_service.infrastructure.db.models import AuthEventModel


def _to_model(dto: AuditEventDTO) -> AuthEventModel:
    return AuthEventModel(
        id=dto.id,
        user_id=dto.user_id,
        event_type=dto.event_type.value,
        session_id=dto.session_id,
        ip_address=dto.ip_address,
        occurred_at=dto.occurred_at,
        metadata_=dto.metadata,
    )


class AuditLogRepository(AuditLogPort):
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def record(self, event: AuditEventDTO) -> None:
        self._session.add(_to_model(event))
        await self._session.flush()

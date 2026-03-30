from abc import ABC, abstractmethod

from auth_service.application.dto import AuditEventDTO


class AuditLogPort(ABC):
    @abstractmethod
    async def record(self, event: AuditEventDTO) -> None:
        """Append an audit event to the durable log."""
        ...

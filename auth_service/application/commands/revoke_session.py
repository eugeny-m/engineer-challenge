import time

from auth_service.application.dto import RevokeSessionCommand
from auth_service.application.ports.token_store import TokenStore
from auth_service.infrastructure.logging import get_logger

_log = get_logger(__name__)


class RevokeSessionHandler:
    def __init__(self, token_store: TokenStore) -> None:
        self._token_store = token_store

    async def handle(self, command: RevokeSessionCommand) -> None:
        start = time.monotonic()
        log = _log.bind(operation="revoke_session", session_id=str(command.session_id))
        log.info("revoke_session.start")

        try:
            await self._token_store.revoke_session(command.session_id)
            duration_ms = round((time.monotonic() - start) * 1000, 2)
            log.info("revoke_session.success", duration_ms=duration_ms)
        except Exception as exc:
            duration_ms = round((time.monotonic() - start) * 1000, 2)
            log.warning("revoke_session.failure", error=str(exc), duration_ms=duration_ms)
            raise

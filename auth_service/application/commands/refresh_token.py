import time
import uuid
from datetime import datetime, timezone
from uuid import UUID

from auth_service.application.dto import AuditEventDTO, RefreshTokenCommand, TokenPairDTO
from auth_service.application.ports.audit_log import AuditLogPort
from auth_service.application.ports.token_service import TokenService
from auth_service.application.ports.token_store import TokenStore
from auth_service.domain.exceptions import InvalidTokenError
from auth_service.domain.value_objects.auth_event_type import AuthEventType
from auth_service.infrastructure.logging import get_logger

_log = get_logger(__name__)

_DEFAULT_ACCESS_TOKEN_TTL = 15 * 60
_DEFAULT_REFRESH_TOKEN_TTL = 30 * 24 * 3600


class RefreshTokenHandler:
    def __init__(
        self,
        token_service: TokenService,
        token_store: TokenStore,
        audit_log: AuditLogPort,
        access_ttl: int = _DEFAULT_ACCESS_TOKEN_TTL,
        refresh_ttl: int = _DEFAULT_REFRESH_TOKEN_TTL,
    ) -> None:
        self._token_service = token_service
        self._token_store = token_store
        self._audit_log = audit_log
        self._access_ttl = access_ttl
        self._refresh_ttl = refresh_ttl

    async def handle(self, command: RefreshTokenCommand) -> TokenPairDTO:
        start = time.monotonic()
        log = _log.bind(operation="refresh_token")
        log.info("refresh_token.start")

        try:
            session_data = await self._token_store.get_session_by_refresh_token(command.refresh_token)
            if session_data is None:
                raise InvalidTokenError("Invalid or expired refresh token")

            user_id = UUID(session_data["user_id"])
            session_id = UUID(session_data["session_id"])

            new_access_token, new_jti = self._token_service.generate_access_token(user_id, session_id)
            new_refresh_token = self._token_service.generate_refresh_token()

            await self._token_store.rotate_session(
                session_id=session_id,
                old_refresh_token=command.refresh_token,
                new_access_jti=new_jti,
                new_refresh_token=new_refresh_token,
                access_ttl=self._access_ttl,
                refresh_ttl=self._refresh_ttl,
            )

            try:
                await self._audit_log.record(
                    AuditEventDTO(
                        id=uuid.uuid4(),
                        event_type=AuthEventType.TOKEN_REFRESHED,
                        occurred_at=datetime.now(timezone.utc),
                        user_id=user_id,
                        session_id=session_id,
                        ip_address=command.ip_address,
                        metadata={},
                    )
                )
            except Exception:
                pass

            duration_ms = round((time.monotonic() - start) * 1000, 2)
            log.info(
                "refresh_token.success",
                user_id=str(user_id),
                session_id=str(session_id),
                duration_ms=duration_ms,
            )
            return TokenPairDTO(
                access_token=new_access_token,
                refresh_token=new_refresh_token,
                session_id=session_id,
            )
        except Exception as exc:
            duration_ms = round((time.monotonic() - start) * 1000, 2)
            log.warning("refresh_token.failure", error=str(exc), duration_ms=duration_ms)
            raise

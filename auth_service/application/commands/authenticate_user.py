import time
import uuid
from datetime import datetime, timezone

from auth_service.application.dto import AuditEventDTO, AuthenticateUserCommand, TokenPairDTO
from auth_service.application.ports.audit_log import AuditLogPort
from auth_service.application.ports.password_hasher import PasswordHasher
from auth_service.application.ports.token_service import TokenService
from auth_service.application.ports.token_store import TokenStore
from auth_service.domain.exceptions import InvalidCredentialsError
from auth_service.domain.repositories.user_repository import UserRepository
from auth_service.domain.value_objects.auth_event_type import AuthEventType
from auth_service.domain.value_objects.email import Email
from auth_service.infrastructure.logging import get_logger

_log = get_logger(__name__)

# Default TTL constants (seconds) — overridden at construction time via container.
_DEFAULT_ACCESS_TOKEN_TTL = 15 * 60       # 15 minutes
_DEFAULT_REFRESH_TOKEN_TTL = 30 * 24 * 3600  # 30 days

# Cached dummy hash — populated lazily on first login attempt for a non-existent user.
# Used to equalise response time regardless of whether the email exists, preventing
# email enumeration via timing side-channel.
_dummy_hash_cache: str = ""


class AuthenticateUserHandler:
    def __init__(
        self,
        user_repo: UserRepository,
        hasher: PasswordHasher,
        token_service: TokenService,
        token_store: TokenStore,
        audit_log: AuditLogPort,
        access_ttl: int = _DEFAULT_ACCESS_TOKEN_TTL,
        refresh_ttl: int = _DEFAULT_REFRESH_TOKEN_TTL,
    ) -> None:
        self._user_repo = user_repo
        self._hasher = hasher
        self._token_service = token_service
        self._token_store = token_store
        self._audit_log = audit_log
        self._access_ttl = access_ttl
        self._refresh_ttl = refresh_ttl

    async def _record_login_failed(
        self,
        user_id: uuid.UUID | None,
        ip_address: str | None,
        reason: str,
    ) -> None:
        try:
            await self._audit_log.record(
                AuditEventDTO(
                    id=uuid.uuid4(),
                    event_type=AuthEventType.LOGIN_FAILED,
                    occurred_at=datetime.now(timezone.utc),
                    user_id=user_id,
                    ip_address=ip_address,
                    metadata={"reason": reason},
                )
            )
        except Exception:
            pass

    async def handle(self, command: AuthenticateUserCommand) -> TokenPairDTO:
        start = time.monotonic()
        log = _log.bind(operation="authenticate_user")
        log.info("authenticate_user.start")

        try:
            email = Email(command.email)
            user = await self._user_repo.find_by_email(email)
            if user is None:
                # Run a dummy verification to equalise timing with the real path,
                # preventing email enumeration via response-time differences.
                global _dummy_hash_cache
                if not _dummy_hash_cache:
                    _dummy_hash_cache = self._hasher.hash("__dummy_timing_guard__")
                self._hasher.verify(command.password, _dummy_hash_cache)
                await self._record_login_failed(None, command.ip_address, "user_not_found")
                raise InvalidCredentialsError("Invalid email or password")

            if not user.is_active:
                await self._record_login_failed(user.id, command.ip_address, "inactive_account")
                raise InvalidCredentialsError("Invalid email or password")

            if not self._hasher.verify(command.password, user.hashed_password.value):
                await self._record_login_failed(user.id, command.ip_address, "invalid_password")
                raise InvalidCredentialsError("Invalid email or password")

            session_id = uuid.uuid4()
            access_token, jti = self._token_service.generate_access_token(user.id, session_id)
            refresh_token = self._token_service.generate_refresh_token()

            device_info = (command.device_info or "")[:512] or None

            await self._token_store.create_session(
                session_id=session_id,
                user_id=user.id,
                access_jti=jti,
                refresh_token=refresh_token,
                device_info=device_info,
                access_ttl=self._access_ttl,
                refresh_ttl=self._refresh_ttl,
            )

            try:
                await self._audit_log.record(
                    AuditEventDTO(
                        id=uuid.uuid4(),
                        event_type=AuthEventType.LOGIN_SUCCESS,
                        occurred_at=datetime.now(timezone.utc),
                        user_id=user.id,
                        session_id=session_id,
                        ip_address=command.ip_address,
                        metadata={"device_info": device_info or ""},
                    )
                )
            except Exception:
                pass

            duration_ms = round((time.monotonic() - start) * 1000, 2)
            log.info(
                "authenticate_user.success",
                user_id=str(user.id),
                session_id=str(session_id),
                duration_ms=duration_ms,
            )
            return TokenPairDTO(
                access_token=access_token,
                refresh_token=refresh_token,
                session_id=session_id,
            )
        except Exception as exc:
            duration_ms = round((time.monotonic() - start) * 1000, 2)
            log.warning("authenticate_user.failure", error=str(exc), duration_ms=duration_ms)
            raise

import time
import uuid

from auth_service.application.dto import AuthenticateUserCommand, TokenPairDTO
from auth_service.application.ports.password_hasher import PasswordHasher
from auth_service.application.ports.token_service import TokenService
from auth_service.application.ports.token_store import TokenStore
from auth_service.domain.exceptions import InvalidCredentialsError
from auth_service.domain.repositories.user_repository import UserRepository
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
        access_ttl: int = _DEFAULT_ACCESS_TOKEN_TTL,
        refresh_ttl: int = _DEFAULT_REFRESH_TOKEN_TTL,
    ) -> None:
        self._user_repo = user_repo
        self._hasher = hasher
        self._token_service = token_service
        self._token_store = token_store
        self._access_ttl = access_ttl
        self._refresh_ttl = refresh_ttl

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
                raise InvalidCredentialsError("Invalid email or password")

            if not user.is_active:
                raise InvalidCredentialsError("Invalid email or password")

            if not self._hasher.verify(command.password, user.hashed_password.value):
                raise InvalidCredentialsError("Invalid email or password")

            session_id = uuid.uuid4()
            access_token = self._token_service.generate_access_token(user.id, session_id)
            refresh_token = self._token_service.generate_refresh_token()

            # Extract jti from access token claims
            claims = self._token_service.decode_access_token(access_token)
            jti = claims["jti"]

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

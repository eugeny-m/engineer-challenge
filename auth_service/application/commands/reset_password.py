import time

from auth_service.application.dto import ResetPasswordCommand
from auth_service.application.ports.password_hasher import PasswordHasher
from auth_service.application.ports.token_store import TokenStore
from auth_service.domain.exceptions import TokenNotFoundError, UserNotFoundError
from auth_service.domain.repositories.reset_token_repository import ResetTokenRepository
from auth_service.domain.repositories.user_repository import UserRepository
from auth_service.domain.value_objects.hashed_password import HashedPassword
from auth_service.domain.value_objects.plain_password import PlainPassword
from auth_service.infrastructure.logging import get_logger

_log = get_logger(__name__)


class ResetPasswordHandler:
    def __init__(
        self,
        reset_token_repo: ResetTokenRepository,
        user_repo: UserRepository,
        hasher: PasswordHasher,
        token_store: TokenStore,
    ) -> None:
        self._reset_token_repo = reset_token_repo
        self._user_repo = user_repo
        self._hasher = hasher
        self._token_store = token_store

    async def handle(self, command: ResetPasswordCommand) -> None:
        start = time.monotonic()
        log = _log.bind(operation="reset_password")
        log.info("reset_password.start")

        try:
            # Validate new password strength before hitting the DB
            PlainPassword(command.new_password)

            reset_token = await self._reset_token_repo.find_by_token(command.token)
            if reset_token is None:
                raise TokenNotFoundError("Reset token not found")

            # consume() enforces TTL and single-use invariants (raises on violation)
            reset_token.consume()

            user = await self._user_repo.find_by_id(reset_token.user_id)
            if user is None:
                raise UserNotFoundError("User associated with reset token not found")

            new_hash = HashedPassword(self._hasher.hash(command.new_password))
            user.change_password(new_hash)
            await self._user_repo.save(user)
            await self._reset_token_repo.save(reset_token)  # persist used=True

            # Force re-login: revoke all active sessions after password change
            await self._token_store.revoke_all_user_sessions(user.id)

            duration_ms = round((time.monotonic() - start) * 1000, 2)
            log.info("reset_password.success", user_id=str(user.id), duration_ms=duration_ms)
        except Exception as exc:
            duration_ms = round((time.monotonic() - start) * 1000, 2)
            log.warning("reset_password.failure", error=str(exc), duration_ms=duration_ms)
            raise

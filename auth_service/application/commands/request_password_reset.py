import hashlib
import secrets
import time
import uuid
from datetime import datetime, timedelta, timezone

from auth_service.application.dto import RequestPasswordResetCommand
from auth_service.application.ports.email_service import EmailService
from auth_service.domain.entities.password_reset_token import PasswordResetToken

from auth_service.domain.repositories.reset_token_repository import ResetTokenRepository
from auth_service.domain.repositories.user_repository import UserRepository
from auth_service.domain.value_objects.email import Email
from auth_service.domain.value_objects.reset_token import ResetToken
from auth_service.infrastructure.logging import get_logger

_log = get_logger(__name__)

RESET_TOKEN_EXPIRE_MINUTES = 15


class RequestPasswordResetHandler:
    def __init__(
        self,
        user_repo: UserRepository,
        reset_token_repo: ResetTokenRepository,
        email_service: EmailService,
        expire_minutes: int = RESET_TOKEN_EXPIRE_MINUTES,
    ) -> None:
        self._user_repo = user_repo
        self._reset_token_repo = reset_token_repo
        self._email_service = email_service
        self._expire_minutes = expire_minutes

    async def handle(self, command: RequestPasswordResetCommand) -> None:
        start = time.monotonic()
        log = _log.bind(operation="request_password_reset")
        log.info("request_password_reset.start")

        try:
            email = Email(command.email)
            user = await self._user_repo.find_by_email(email)

            # Silently return when the email is not registered to prevent email enumeration.
            # Callers receive a success response regardless, so they cannot distinguish
            # between a registered and unregistered address.
            if user is None:
                duration_ms = round((time.monotonic() - start) * 1000, 2)
                log.info("request_password_reset.no_account", duration_ms=duration_ms)
                return

            # Invalidate all previous reset tokens for this user (one active token invariant)
            await self._reset_token_repo.delete_all_by_user_id(user.id)

            raw_token = secrets.token_urlsafe(32)
            # Store only a SHA-256 hash in the database so that a DB breach does not
            # expose usable reset tokens.  The raw token is sent to the user's email
            # and never persisted.
            token_hash = hashlib.sha256(raw_token.encode()).hexdigest()
            token_value = ResetToken(value=token_hash)
            expires_at = datetime.now(timezone.utc) + timedelta(minutes=self._expire_minutes)
            reset_token = PasswordResetToken(
                id=uuid.uuid4(),
                user_id=user.id,
                token=token_value,
                expires_at=expires_at,
                used=False,
            )
            await self._reset_token_repo.save(reset_token)
            await self._email_service.send_reset_email(email.value, raw_token)

            duration_ms = round((time.monotonic() - start) * 1000, 2)
            log.info(
                "request_password_reset.success",
                user_id=str(user.id),
                duration_ms=duration_ms,
            )
        except Exception as exc:
            duration_ms = round((time.monotonic() - start) * 1000, 2)
            log.warning("request_password_reset.failure", error=str(exc), duration_ms=duration_ms)
            raise

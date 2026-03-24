import secrets
import uuid
from datetime import datetime, timedelta, timezone

from auth_service.application.dto import RequestPasswordResetCommand
from auth_service.application.ports.email_service import EmailService
from auth_service.domain.entities.password_reset_token import PasswordResetToken
from auth_service.domain.exceptions import UserNotFoundError
from auth_service.domain.repositories.reset_token_repository import ResetTokenRepository
from auth_service.domain.repositories.user_repository import UserRepository
from auth_service.domain.value_objects.email import Email
from auth_service.domain.value_objects.reset_token import ResetToken

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
        email = Email(command.email)
        user = await self._user_repo.find_by_email(email)

        # Product decision: raise UserNotFoundError on unknown email for UX clarity.
        # Trade-off: the security-correct approach would silently return to prevent email
        # enumeration. Change raise to `return` if the threat model requires it.
        if user is None:
            raise UserNotFoundError(f"No account found for email {email.value}")

        # Invalidate all previous reset tokens for this user (one active token invariant)
        await self._reset_token_repo.delete_all_by_user_id(user.id)

        token_value = ResetToken(value=secrets.token_urlsafe(32))
        expires_at = datetime.now(timezone.utc) + timedelta(minutes=self._expire_minutes)
        reset_token = PasswordResetToken(
            id=uuid.uuid4(),
            user_id=user.id,
            token=token_value,
            expires_at=expires_at,
            used=False,
        )
        await self._reset_token_repo.save(reset_token)
        await self._email_service.send_reset_email(email.value, token_value.value)

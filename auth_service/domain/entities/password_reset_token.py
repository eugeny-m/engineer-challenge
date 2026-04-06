from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import UUID

from auth_service.domain.exceptions import TokenAlreadyUsedError, TokenExpiredError
from auth_service.domain.value_objects.reset_token import ResetToken


@dataclass
class PasswordResetToken:
    id: UUID
    user_id: UUID
    token: ResetToken
    expires_at: datetime
    used: bool

    def consume(self) -> None:
        now = datetime.now(timezone.utc)
        if now >= self.expires_at:
            raise TokenExpiredError("Reset token has expired")
        if self.used:
            raise TokenAlreadyUsedError("Reset token has already been used")
        self.used = True

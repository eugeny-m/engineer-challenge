from abc import ABC, abstractmethod
from uuid import UUID

from auth_service.domain.entities.password_reset_token import PasswordResetToken


class ResetTokenRepository(ABC):
    @abstractmethod
    async def save(self, token: PasswordResetToken) -> None: ...

    @abstractmethod
    async def find_by_token(self, token_str: str) -> PasswordResetToken | None: ...

    @abstractmethod
    async def delete_all_by_user_id(self, user_id: UUID) -> None:
        """Deletes ALL tokens for the user regardless of expiry or used status.
        Invariant: only one pending reset token per user at any time; issuing a new one
        unconditionally invalidates all previous ones."""
        ...

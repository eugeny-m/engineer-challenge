from abc import ABC, abstractmethod


class EmailService(ABC):
    @abstractmethod
    async def send_reset_email(self, to_email: str, reset_token: str) -> None:
        """Send a password reset email containing the reset token."""
        ...

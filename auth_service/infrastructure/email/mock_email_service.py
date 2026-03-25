import structlog

from auth_service.application.ports.email_service import EmailService

logger = structlog.get_logger(__name__)


class MockEmailService(EmailService):
    """Development email service — logs the reset link instead of sending real email.

    TODO: replace with real SMTP adapter (e.g. SendGrid, AWS SES) for production.
    """

    def __init__(self) -> None:
        # (to_email, raw_reset_token) pairs — useful for integration tests that need
        # the raw token without touching the database.
        self.sent_emails: list[tuple[str, str]] = []

    async def send_reset_email(self, to_email: str, reset_token: str) -> None:
        self.sent_emails.append((to_email, reset_token))
        logger.info(
            "password_reset_email_sent",
            to_email=to_email,
            reset_token_prefix=reset_token[:8] + "...",
            note="MOCK — no real email sent",
        )

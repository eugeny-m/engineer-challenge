import structlog

from auth_service.application.ports.email_service import EmailService

logger = structlog.get_logger(__name__)


class MockEmailService(EmailService):
    """Development email service — logs the reset link instead of sending real email.

    TODO: replace with real SMTP adapter (e.g. SendGrid, AWS SES) for production.
    """

    async def send_reset_email(self, to_email: str, reset_token: str) -> None:
        logger.info(
            "password_reset_email_sent",
            to_email=to_email,
            reset_token_prefix=reset_token[:8] + "...",
            note="MOCK — no real email sent",
        )

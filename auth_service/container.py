"""Dependency injection container — instantiates and wires all service components.

Architecture: two-level container.

GlobalContainer: singletons that live for the app lifetime (Redis, hasher, token
service, email service, session factory).

RequestScope: created per GraphQL request, holds the DB session and all
command handlers that depend on it. On exit the session is committed or
rolled back depending on whether an exception occurred.
"""
from __future__ import annotations

import os
from contextlib import asynccontextmanager
from typing import AsyncGenerator

import redis.asyncio as aioredis
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from auth_service.application.commands.authenticate_user import AuthenticateUserHandler
from auth_service.application.commands.refresh_token import RefreshTokenHandler
from auth_service.application.commands.register_user import RegisterUserHandler
from auth_service.application.commands.request_password_reset import RequestPasswordResetHandler
from auth_service.application.commands.reset_password import ResetPasswordHandler
from auth_service.application.commands.revoke_session import RevokeSessionHandler
from auth_service.application.ports.audit_log import AuditLogPort
from auth_service.application.ports.token_service import TokenService
from auth_service.application.ports.token_store import TokenStore
from auth_service.infrastructure.db.repositories.audit_log_repository import AuditLogRepository
from auth_service.infrastructure.db.repositories.reset_token_repository import (
    SqlResetTokenRepository,
)
from auth_service.infrastructure.db.repositories.user_repository import SqlUserRepository
from auth_service.infrastructure.email.mock_email_service import MockEmailService
from auth_service.infrastructure.redis.redis_token_store import RedisTokenStore
from auth_service.infrastructure.security.bcrypt_hasher import BcryptHasher
from auth_service.infrastructure.security.jwt_token_service import JwtTokenService
from auth_service.infrastructure.security.rate_limiter import RateLimiter


class RequestScope:
    """Per-request scope: holds a DB session and all command handlers."""

    def __init__(
        self,
        session: AsyncSession,
        global_container: "GlobalContainer",
    ) -> None:
        self._session = session
        self.token_service = global_container.token_service
        self.token_store = global_container.token_store

        # Per-request repositories (bound to the session)
        self.user_repo = SqlUserRepository(session)
        self._reset_token_repo = SqlResetTokenRepository(session)
        self.audit_log: AuditLogPort = AuditLogRepository(session)

        # Command handlers
        self.register_user_handler = RegisterUserHandler(
            user_repo=self.user_repo,
            hasher=global_container.hasher,
        )
        self.authenticate_user_handler = AuthenticateUserHandler(
            user_repo=self.user_repo,
            hasher=global_container.hasher,
            token_service=global_container.token_service,
            token_store=global_container.token_store,
            audit_log=self.audit_log,
            access_ttl=global_container.access_token_ttl_seconds,
            refresh_ttl=global_container.refresh_token_ttl_seconds,
        )
        self.refresh_token_handler = RefreshTokenHandler(
            token_service=global_container.token_service,
            token_store=global_container.token_store,
            audit_log=self.audit_log,
            access_ttl=global_container.access_token_ttl_seconds,
            refresh_ttl=global_container.refresh_token_ttl_seconds,
        )
        self.revoke_session_handler = RevokeSessionHandler(
            token_store=global_container.token_store,
            audit_log=self.audit_log,
        )
        self.request_password_reset_handler = RequestPasswordResetHandler(
            user_repo=self.user_repo,
            reset_token_repo=self._reset_token_repo,
            email_service=global_container.email_service,
            audit_log=self.audit_log,
            expire_minutes=global_container.reset_token_expire_minutes,
        )
        self.reset_password_handler = ResetPasswordHandler(
            user_repo=self.user_repo,
            reset_token_repo=self._reset_token_repo,
            hasher=global_container.hasher,
            token_store=global_container.token_store,
            audit_log=self.audit_log,
        )


class GlobalContainer:
    """App-lifetime singletons — created once at startup."""

    def __init__(
        self,
        redis_client: aioredis.Redis,
        session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        self._session_factory = session_factory

        jwt_secret = os.environ.get("JWT_SECRET")
        if not jwt_secret:
            raise RuntimeError("JWT_SECRET environment variable must be set")
        access_ttl_minutes = int(os.environ.get("ACCESS_TOKEN_EXPIRE_MINUTES", "15"))
        refresh_ttl_days = int(os.environ.get("REFRESH_TOKEN_EXPIRE_DAYS", "30"))
        reset_token_expire_minutes = int(os.environ.get("RESET_TOKEN_EXPIRE_MINUTES", "15"))

        self.access_token_ttl_seconds = access_ttl_minutes * 60
        self.refresh_token_ttl_seconds = refresh_ttl_days * 24 * 3600
        self.reset_token_expire_minutes = reset_token_expire_minutes

        self.hasher = BcryptHasher()
        self.token_service: TokenService = JwtTokenService(
            secret=jwt_secret,
            access_token_expire_minutes=access_ttl_minutes,
        )
        self.token_store: TokenStore = RedisTokenStore(redis_client)
        # MockEmailService logs tokens to stdout; suitable for development only.
        # Set EMAIL_BACKEND=smtp (and configure SMTP_* vars) for production.
        # TODO: add SmtpEmailService and select based on EMAIL_BACKEND env var.
        self.email_service = MockEmailService()
        self.rate_limiter = RateLimiter(redis_client)

    @asynccontextmanager
    async def request_scope(self) -> AsyncGenerator[RequestScope, None]:
        """Open a DB session for one request, commit on success, rollback on error."""
        async with self._session_factory() as session:
            async with session.begin():
                yield RequestScope(session=session, global_container=self)


# ---------------------------------------------------------------------------
# Module-level singleton — populated during FastAPI lifespan
# ---------------------------------------------------------------------------

_global_container: GlobalContainer | None = None


def get_global_container() -> GlobalContainer:
    if _global_container is None:
        raise RuntimeError("GlobalContainer not initialised — did lifespan startup run?")
    return _global_container


def set_global_container(container: GlobalContainer) -> None:
    global _global_container
    _global_container = container

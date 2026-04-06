from dataclasses import dataclass, field
from datetime import datetime
from uuid import UUID

from auth_service.domain.value_objects.auth_event_type import AuthEventType


@dataclass(frozen=True)
class RegisterUserCommand:
    email: str
    password: str


@dataclass(frozen=True)
class AuthenticateUserCommand:
    email: str
    password: str
    device_info: str | None = None
    ip_address: str | None = None


@dataclass(frozen=True)
class RefreshTokenCommand:
    refresh_token: str
    ip_address: str | None = None


@dataclass(frozen=True)
class RevokeSessionCommand:
    session_id: UUID
    ip_address: str | None = None


@dataclass(frozen=True)
class RequestPasswordResetCommand:
    email: str
    ip_address: str | None = None


@dataclass(frozen=True)
class ResetPasswordCommand:
    token: str
    new_password: str
    ip_address: str | None = None


@dataclass(frozen=True)
class AuditEventDTO:
    id: UUID
    event_type: AuthEventType
    occurred_at: datetime
    user_id: UUID | None = None
    session_id: UUID | None = None
    ip_address: str | None = None
    metadata: dict = field(default_factory=dict)


@dataclass(frozen=True)
class TokenPairDTO:
    access_token: str
    refresh_token: str
    session_id: UUID
    token_type: str = "Bearer"

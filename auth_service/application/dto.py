from dataclasses import dataclass, field
from uuid import UUID


@dataclass(frozen=True)
class RegisterUserCommand:
    email: str
    password: str


@dataclass(frozen=True)
class AuthenticateUserCommand:
    email: str
    password: str
    device_info: str | None = None


@dataclass(frozen=True)
class RefreshTokenCommand:
    refresh_token: str


@dataclass(frozen=True)
class RevokeSessionCommand:
    session_id: UUID


@dataclass(frozen=True)
class RequestPasswordResetCommand:
    email: str


@dataclass(frozen=True)
class ResetPasswordCommand:
    token: str
    new_password: str


@dataclass(frozen=True)
class TokenPairDTO:
    access_token: str
    refresh_token: str
    session_id: UUID
    token_type: str = "Bearer"

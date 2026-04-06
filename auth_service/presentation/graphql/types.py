"""Strawberry GraphQL input and output types for the auth service."""
from __future__ import annotations

import strawberry


# ---------------------------------------------------------------------------
# Input types
# ---------------------------------------------------------------------------

@strawberry.input
class RegisterInput:
    email: str
    password: str


@strawberry.input
class LoginInput:
    email: str
    password: str
    device_info: str | None = None


@strawberry.input
class RefreshTokenInput:
    refresh_token: str


@strawberry.input
class RevokeSessionInput:
    session_id: strawberry.ID


@strawberry.input
class RequestResetInput:
    email: str


@strawberry.input
class ResetPasswordInput:
    token: str
    new_password: str


# ---------------------------------------------------------------------------
# Output types
# ---------------------------------------------------------------------------

@strawberry.type
class AuthPayload:
    access_token: str
    refresh_token: str
    session_id: strawberry.ID
    token_type: str


@strawberry.type
class OperationResult:
    success: bool
    message: str


@strawberry.type
class UserInfo:
    id: strawberry.ID
    email: str
    is_active: bool

"""Strawberry GraphQL mutation resolvers."""
from __future__ import annotations

from uuid import UUID

import strawberry
from strawberry.types import Info

from auth_service.application.commands.authenticate_user import AuthenticateUserHandler
from auth_service.application.commands.refresh_token import RefreshTokenHandler
from auth_service.application.commands.register_user import RegisterUserHandler
from auth_service.application.commands.request_password_reset import RequestPasswordResetHandler
from auth_service.application.commands.reset_password import ResetPasswordHandler
from auth_service.application.commands.revoke_session import RevokeSessionHandler
from auth_service.application.dto import (
    AuthenticateUserCommand,
    RefreshTokenCommand,
    RegisterUserCommand,
    RequestPasswordResetCommand,
    ResetPasswordCommand,
    RevokeSessionCommand,
)
from auth_service.domain.exceptions import (
    InvalidCredentialsError,
    InvalidEmailError,
    InvalidTokenError,
    TokenAlreadyUsedError,
    TokenExpiredError,
    TokenNotFoundError,
    UserAlreadyExistsError,
    UserNotFoundError,
    WeakPasswordError,
)
from auth_service.presentation.graphql.types import (
    AuthPayload,
    LoginInput,
    OperationResult,
    RefreshTokenInput,
    RegisterInput,
    RequestResetInput,
    ResetPasswordInput,
    RevokeSessionInput,
)


@strawberry.type
class AuthMutation:
    @strawberry.mutation
    async def register(self, info: Info, input: RegisterInput) -> OperationResult:
        container = info.context["container"]
        handler: RegisterUserHandler = container.register_user_handler
        try:
            await handler.handle(RegisterUserCommand(email=input.email, password=input.password))
            return OperationResult(success=True, message="User registered successfully")
        except (InvalidEmailError, WeakPasswordError) as exc:
            return OperationResult(success=False, message=str(exc))
        except UserAlreadyExistsError as exc:
            return OperationResult(success=False, message=str(exc))

    @strawberry.mutation
    async def login(self, info: Info, input: LoginInput) -> AuthPayload:
        container = info.context["container"]
        handler: AuthenticateUserHandler = container.authenticate_user_handler
        try:
            result = await handler.handle(
                AuthenticateUserCommand(
                    email=input.email,
                    password=input.password,
                    device_info=input.device_info,
                )
            )
            return AuthPayload(
                access_token=result.access_token,
                refresh_token=result.refresh_token,
                session_id=strawberry.ID(str(result.session_id)),
                token_type=result.token_type,
            )
        except (InvalidCredentialsError, InvalidEmailError) as exc:
            raise strawberry.exceptions.StrawberryGraphQLError(str(exc)) from exc

    @strawberry.mutation
    async def refresh_token(self, info: Info, input: RefreshTokenInput) -> AuthPayload:
        container = info.context["container"]
        handler: RefreshTokenHandler = container.refresh_token_handler
        try:
            result = await handler.handle(RefreshTokenCommand(refresh_token=input.refresh_token))
            return AuthPayload(
                access_token=result.access_token,
                refresh_token=result.refresh_token,
                session_id=strawberry.ID(str(result.session_id)),
                token_type=result.token_type,
            )
        except InvalidTokenError as exc:
            raise strawberry.exceptions.StrawberryGraphQLError(str(exc)) from exc

    @strawberry.mutation
    async def revoke_session(self, info: Info, input: RevokeSessionInput) -> OperationResult:
        request = info.context["request"]
        container = info.context["container"]

        # Require a valid Bearer token; verify the session belongs to the caller.
        auth_header = request.headers.get("Authorization", "")
        if not auth_header.startswith("Bearer "):
            return OperationResult(success=False, message="Authentication required")
        token = auth_header.removeprefix("Bearer ").strip()
        try:
            claims = container.token_service.decode_access_token(token)
        except (TokenExpiredError, InvalidTokenError):
            return OperationResult(success=False, message="Authentication required")

        caller_user_id_str = claims.get("sub")
        jti = claims.get("jti")
        if not caller_user_id_str or not jti:
            return OperationResult(success=False, message="Authentication required")
        if not await container.token_store.is_access_jti_valid(jti):
            return OperationResult(success=False, message="Authentication required")

        session_id = UUID(str(input.session_id))
        session_data = await container.token_store.get_session(session_id)
        if session_data is None:
            return OperationResult(success=False, message="Session not found")
        if session_data.get("user_id") != caller_user_id_str:
            return OperationResult(success=False, message="Not authorised to revoke this session")

        handler: RevokeSessionHandler = container.revoke_session_handler
        try:
            await handler.handle(RevokeSessionCommand(session_id=session_id))
            return OperationResult(success=True, message="Session revoked")
        except Exception:
            return OperationResult(success=False, message="Internal error")

    @strawberry.mutation
    async def request_password_reset(
        self, info: Info, input: RequestResetInput
    ) -> OperationResult:
        container = info.context["container"]
        handler: RequestPasswordResetHandler = container.request_password_reset_handler
        try:
            await handler.handle(RequestPasswordResetCommand(email=input.email))
            return OperationResult(success=True, message="Password reset email sent")
        except InvalidEmailError as exc:
            return OperationResult(success=False, message=str(exc))

    @strawberry.mutation
    async def reset_password(self, info: Info, input: ResetPasswordInput) -> OperationResult:
        container = info.context["container"]
        handler: ResetPasswordHandler = container.reset_password_handler
        try:
            await handler.handle(
                ResetPasswordCommand(token=input.token, new_password=input.new_password)
            )
            return OperationResult(success=True, message="Password reset successfully")
        except TokenExpiredError as exc:
            return OperationResult(success=False, message=str(exc))
        except TokenAlreadyUsedError as exc:
            return OperationResult(success=False, message=str(exc))
        except (TokenNotFoundError, UserNotFoundError, WeakPasswordError, InvalidTokenError) as exc:
            return OperationResult(success=False, message=str(exc))

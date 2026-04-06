"""Strawberry GraphQL query resolvers."""
from __future__ import annotations

from uuid import UUID

import strawberry
from strawberry.types import Info

from auth_service.domain.exceptions import InvalidTokenError, TokenExpiredError
from auth_service.domain.value_objects.email import Email
from auth_service.presentation.graphql.types import UserInfo


@strawberry.type
class AuthQuery:
    @strawberry.field
    async def me(self, info: Info) -> UserInfo | None:
        """Return current user info if the JWT is valid and jti is in Redis allowlist."""
        request = info.context["request"]
        container = info.context["container"]

        auth_header = request.headers.get("Authorization", "")
        if not auth_header.startswith("Bearer "):
            return None

        token = auth_header.removeprefix("Bearer ").strip()
        if not token:
            return None

        try:
            claims = container.token_service.decode_access_token(token)
        except (TokenExpiredError, InvalidTokenError):
            return None

        jti = claims.get("jti")
        user_id_str = claims.get("sub")
        if not jti or not user_id_str:
            return None

        # Redis allowlist check — ensures revoked tokens are rejected immediately
        if not await container.token_store.is_access_jti_valid(jti):
            return None

        user = await container.user_repo.find_by_id(UUID(user_id_str))
        if user is None or not user.is_active:
            return None

        return UserInfo(
            id=strawberry.ID(str(user.id)),
            email=user.email.value,
            is_active=user.is_active,
        )

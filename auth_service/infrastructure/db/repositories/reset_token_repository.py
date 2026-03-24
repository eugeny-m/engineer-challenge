from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from auth_service.domain.entities.password_reset_token import PasswordResetToken
from auth_service.domain.repositories.reset_token_repository import ResetTokenRepository
from auth_service.domain.value_objects.reset_token import ResetToken
from auth_service.infrastructure.db.models import PasswordResetTokenModel


def _to_domain(model: PasswordResetTokenModel) -> PasswordResetToken:
    return PasswordResetToken(
        id=model.id,
        user_id=model.user_id,
        token=ResetToken(model.token),
        expires_at=model.expires_at,
        used=model.used,
    )


def _to_model(token: PasswordResetToken) -> PasswordResetTokenModel:
    return PasswordResetTokenModel(
        id=token.id,
        user_id=token.user_id,
        token=token.token.value,
        expires_at=token.expires_at,
        used=token.used,
    )


class SqlResetTokenRepository(ResetTokenRepository):
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def save(self, token: PasswordResetToken) -> None:
        existing = await self._session.get(PasswordResetTokenModel, token.id)
        if existing is None:
            self._session.add(_to_model(token))
        else:
            existing.token = token.token.value
            existing.expires_at = token.expires_at
            existing.used = token.used
        await self._session.flush()

    async def find_by_token(self, token_str: str) -> PasswordResetToken | None:
        result = await self._session.execute(
            select(PasswordResetTokenModel).where(PasswordResetTokenModel.token == token_str)
        )
        model = result.scalar_one_or_none()
        return _to_domain(model) if model is not None else None

    async def delete_all_by_user_id(self, user_id: UUID) -> None:
        await self._session.execute(
            delete(PasswordResetTokenModel).where(PasswordResetTokenModel.user_id == user_id)
        )
        await self._session.flush()

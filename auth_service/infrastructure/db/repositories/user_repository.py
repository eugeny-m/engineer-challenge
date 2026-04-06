from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from auth_service.domain.entities.user import User
from auth_service.domain.repositories.user_repository import UserRepository
from auth_service.domain.value_objects.email import Email
from auth_service.domain.value_objects.hashed_password import HashedPassword
from auth_service.infrastructure.db.models import UserModel


def _to_domain(model: UserModel) -> User:
    return User(
        id=model.id,
        email=Email(model.email),
        hashed_password=HashedPassword(model.hashed_password),
        is_active=model.is_active,
        created_at=model.created_at,
    )


def _to_model(user: User) -> UserModel:
    return UserModel(
        id=user.id,
        email=user.email.value,
        hashed_password=user.hashed_password.value,
        is_active=user.is_active,
        created_at=user.created_at,
    )


class SqlUserRepository(UserRepository):
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def save(self, user: User) -> None:
        existing = await self._session.get(UserModel, user.id)
        if existing is None:
            self._session.add(_to_model(user))
        else:
            existing.email = user.email.value
            existing.hashed_password = user.hashed_password.value
            existing.is_active = user.is_active
            existing.created_at = user.created_at
        await self._session.flush()

    async def find_by_email(self, email: Email) -> User | None:
        result = await self._session.execute(
            select(UserModel).where(UserModel.email == email.value)
        )
        model = result.scalar_one_or_none()
        return _to_domain(model) if model is not None else None

    async def find_by_id(self, user_id: UUID) -> User | None:
        model = await self._session.get(UserModel, user_id)
        return _to_domain(model) if model is not None else None

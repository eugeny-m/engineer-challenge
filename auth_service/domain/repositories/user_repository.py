from abc import ABC, abstractmethod
from uuid import UUID

from auth_service.domain.entities.user import User
from auth_service.domain.value_objects.email import Email


class UserRepository(ABC):
    @abstractmethod
    async def save(self, user: User) -> None: ...

    @abstractmethod
    async def find_by_email(self, email: Email) -> User | None: ...

    @abstractmethod
    async def find_by_id(self, user_id: UUID) -> User | None: ...

import uuid
from datetime import datetime, timezone

from auth_service.application.dto import RegisterUserCommand
from auth_service.application.ports.password_hasher import PasswordHasher
from auth_service.domain.entities.user import User
from auth_service.domain.exceptions import UserAlreadyExistsError
from auth_service.domain.repositories.user_repository import UserRepository
from auth_service.domain.value_objects.email import Email
from auth_service.domain.value_objects.hashed_password import HashedPassword
from auth_service.domain.value_objects.plain_password import PlainPassword


class RegisterUserHandler:
    def __init__(self, user_repo: UserRepository, hasher: PasswordHasher) -> None:
        self._user_repo = user_repo
        self._hasher = hasher

    async def handle(self, command: RegisterUserCommand) -> None:
        email = Email(command.email)
        PlainPassword(command.password)  # validates invariants; raises WeakPasswordError if invalid

        existing = await self._user_repo.find_by_email(email)
        if existing is not None:
            raise UserAlreadyExistsError(f"User with email {email.value} already exists")

        hashed = HashedPassword(self._hasher.hash(command.password))
        user = User(
            id=uuid.uuid4(),
            email=email,
            hashed_password=hashed,
            is_active=True,
            created_at=datetime.now(timezone.utc),
        )
        await self._user_repo.save(user)

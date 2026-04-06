from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from auth_service.domain.value_objects.email import Email
from auth_service.domain.value_objects.hashed_password import HashedPassword


@dataclass
class User:
    id: UUID
    email: Email
    hashed_password: HashedPassword
    is_active: bool
    created_at: datetime

    def change_password(self, new_hash: HashedPassword) -> None:
        self.hashed_password = new_hash

    def deactivate(self) -> None:
        self.is_active = False

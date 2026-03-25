"""In-memory fakes for unit testing command handlers."""
import uuid
from typing import Any
from uuid import UUID

from auth_service.application.ports.email_service import EmailService
from auth_service.application.ports.password_hasher import PasswordHasher
from auth_service.application.ports.token_service import TokenService
from auth_service.application.ports.token_store import TokenStore
from auth_service.domain.entities.password_reset_token import PasswordResetToken
from auth_service.domain.entities.user import User
from auth_service.domain.repositories.reset_token_repository import ResetTokenRepository
from auth_service.domain.repositories.user_repository import UserRepository
from auth_service.domain.value_objects.email import Email


class FakeUserRepository(UserRepository):
    def __init__(self):
        # keyed by user id
        self.users: dict[UUID, User] = {}

    async def save(self, user: User) -> None:
        self.users[user.id] = user

    async def find_by_email(self, email: Email) -> User | None:
        for user in self.users.values():
            if user.email.value == email.value:
                return user
        return None

    async def find_by_id(self, user_id: UUID) -> User | None:
        return self.users.get(user_id)


class FakeResetTokenRepository(ResetTokenRepository):
    def __init__(self):
        # keyed by token string value
        self.tokens: dict[str, PasswordResetToken] = {}

    async def save(self, token: PasswordResetToken) -> None:
        self.tokens[token.token.value] = token

    async def find_by_token(self, token_str: str) -> PasswordResetToken | None:
        return self.tokens.get(token_str)

    async def delete_all_by_user_id(self, user_id: UUID) -> None:
        to_delete = [k for k, t in self.tokens.items() if t.user_id == user_id]
        for k in to_delete:
            del self.tokens[k]


class FakePasswordHasher(PasswordHasher):
    """Trivial hasher: stores "hashed:<plain>" as the hash for easy verification."""

    def hash(self, plain_password: str) -> str:
        return f"hashed:{plain_password}"

    def verify(self, plain_password: str, hashed_password: str) -> bool:
        return hashed_password == f"hashed:{plain_password}"


class FakeTokenService(TokenService):
    """Generates predictable tokens for unit tests."""

    def generate_access_token(self, user_id: UUID, session_id: UUID) -> str:
        jti = str(uuid.uuid4())
        # Encode a simple "jwt" as "access:{user_id}:{session_id}:{jti}"
        return f"access:{user_id}:{session_id}:{jti}"

    def generate_refresh_token(self) -> str:
        return f"refresh:{uuid.uuid4()}"

    def decode_access_token(self, token: str) -> dict:
        # Parse our fake format: access:{user_id}:{session_id}:{jti}
        parts = token.split(":")
        if len(parts) != 4 or parts[0] != "access":
            from auth_service.domain.exceptions import InvalidTokenError
            raise InvalidTokenError("Invalid token format")
        return {
            "sub": parts[1],
            "sid": parts[2],
            "jti": parts[3],
        }


class FakeTokenStore(TokenStore):
    def __init__(self):
        # session_id -> {user_id, jti, refresh, device_info, ...}
        self.sessions: dict[UUID, dict] = {}
        # jti -> session_id
        self.access_jtis: dict[str, UUID] = {}
        # refresh_token -> {user_id, session_id}
        self.refresh_tokens: dict[str, dict] = {}
        # user_id -> set of session_ids
        self.user_sessions: dict[UUID, set] = {}

    async def create_session(
        self,
        session_id: UUID,
        user_id: UUID,
        access_jti: str,
        refresh_token: str,
        device_info: str | None,
        access_ttl: int,
        refresh_ttl: int,
    ) -> None:
        self.sessions[session_id] = {
            "user_id": user_id,
            "jti": access_jti,
            "refresh": refresh_token,
            "device_info": device_info,
        }
        self.access_jtis[access_jti] = session_id
        self.refresh_tokens[refresh_token] = {"user_id": user_id, "session_id": session_id}
        self.user_sessions.setdefault(user_id, set()).add(session_id)

    async def get_session(self, session_id: UUID) -> dict | None:
        return self.sessions.get(session_id)

    async def is_access_jti_valid(self, jti: str) -> bool:
        return jti in self.access_jtis

    async def get_session_by_refresh_token(self, refresh_token: str) -> dict | None:
        # Pop the token to simulate GETDEL (single-use enforcement)
        data = self.refresh_tokens.pop(refresh_token, None)
        if data is None:
            return None
        # Return string values to match the real Redis implementation contract
        return {"user_id": str(data["user_id"]), "session_id": str(data["session_id"])}

    async def rotate_session(
        self,
        session_id: UUID,
        old_refresh_token: str,
        new_access_jti: str,
        new_refresh_token: str,
        access_ttl: int,
        refresh_ttl: int,
    ) -> None:
        # Remove old refresh
        self.refresh_tokens.pop(old_refresh_token, None)

        session = self.sessions.get(session_id)
        if session:
            old_jti = session.get("jti")
            if old_jti:
                self.access_jtis.pop(old_jti, None)

            session["jti"] = new_access_jti
            session["refresh"] = new_refresh_token

        user_id = session["user_id"] if session else None
        self.access_jtis[new_access_jti] = session_id
        if user_id is not None:
            self.refresh_tokens[new_refresh_token] = {"user_id": user_id, "session_id": session_id}

    async def revoke_session(self, session_id: UUID) -> None:
        session = self.sessions.pop(session_id, None)
        if session is None:
            return
        jti = session.get("jti")
        refresh = session.get("refresh")
        user_id = session.get("user_id")
        if jti:
            self.access_jtis.pop(jti, None)
        if refresh:
            self.refresh_tokens.pop(refresh, None)
        if user_id and user_id in self.user_sessions:
            self.user_sessions[user_id].discard(session_id)

    async def revoke_all_user_sessions(self, user_id: UUID) -> None:
        session_ids = list(self.user_sessions.get(user_id, set()))
        for sid in session_ids:
            await self.revoke_session(sid)
        self.user_sessions.pop(user_id, None)


class FakeEmailService(EmailService):
    def __init__(self):
        self.sent_emails: list[tuple[str, str]] = []

    async def send_reset_email(self, to_email: str, reset_token: str) -> None:
        self.sent_emails.append((to_email, reset_token))

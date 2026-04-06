from abc import ABC, abstractmethod
from uuid import UUID


class TokenStore(ABC):
    @abstractmethod
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
        """Store all session keys atomically.

        Keys written:
          SETEX access:{jti}           → {user_id, session_id}   TTL=access_ttl
          SETEX refresh:{token}        → {user_id, session_id}   TTL=refresh_ttl
          HSET  session:{session_id}   → {user_id, device_info, created_at, last_used}
          SADD  sessions:{user_id}     → session_id
        """
        ...

    @abstractmethod
    async def get_session(self, session_id: UUID) -> dict | None:
        """Return session metadata or None if not found."""
        ...

    @abstractmethod
    async def is_access_jti_valid(self, jti: str) -> bool:
        """Return True if the access jti exists in Redis (allowlist check)."""
        ...

    @abstractmethod
    async def rotate_session(
        self,
        session_id: UUID,
        old_refresh_token: str,
        new_access_jti: str,
        new_refresh_token: str,
        access_ttl: int,
        refresh_ttl: int,
    ) -> None:
        """Atomic rotation: DEL old refresh, SET new access+refresh, update session last_used."""
        ...

    @abstractmethod
    async def revoke_session(self, session_id: UUID) -> None:
        """DEL access jti, refresh token, session hash; SREM from user set."""
        ...

    @abstractmethod
    async def get_session_by_refresh_token(self, refresh_token: str) -> dict | None:
        """Return {user_id, session_id} stored under refresh:{token}, or None."""
        ...

    @abstractmethod
    async def revoke_all_user_sessions(self, user_id: UUID) -> None:
        """SMEMBERS sessions:{user_id} → revoke each session; DEL sessions:{user_id}."""
        ...

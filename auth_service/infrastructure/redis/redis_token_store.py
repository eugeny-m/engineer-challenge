"""Redis-backed token store implementing TokenStore port."""
from datetime import datetime, timezone
from uuid import UUID

import redis.asyncio as aioredis

from auth_service.application.ports.token_store import TokenStore


class RedisTokenStore(TokenStore):
    def __init__(self, redis_client: aioredis.Redis) -> None:
        self._redis = redis_client

    # ------------------------------------------------------------------
    # Key helpers
    # ------------------------------------------------------------------
    @staticmethod
    def _access_key(jti: str) -> str:
        return f"access:{jti}"

    @staticmethod
    def _refresh_key(token: str) -> str:
        return f"refresh:{token}"

    @staticmethod
    def _session_key(session_id: UUID) -> str:
        return f"session:{session_id}"

    @staticmethod
    def _user_sessions_key(user_id: UUID) -> str:
        return f"sessions:{user_id}"

    # ------------------------------------------------------------------
    # Interface implementation
    # ------------------------------------------------------------------

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
        now_iso = datetime.now(tz=timezone.utc).isoformat()
        async with self._redis.pipeline(transaction=True) as pipe:
            # access jti allowlist
            pipe.setex(self._access_key(access_jti), access_ttl, f"{user_id}:{session_id}")
            # refresh token → session mapping
            pipe.setex(self._refresh_key(refresh_token), refresh_ttl, f"{user_id}:{session_id}")
            # session metadata hash (includes jti + refresh refs for revocation)
            pipe.hset(
                self._session_key(session_id),
                mapping={
                    "user_id": str(user_id),
                    "device_info": device_info or "",
                    "created_at": now_iso,
                    "last_used": now_iso,
                    "current_jti": access_jti,
                    "current_refresh": refresh_token,
                },
            )
            pipe.expire(self._session_key(session_id), refresh_ttl)
            # user sessions set
            pipe.sadd(self._user_sessions_key(user_id), str(session_id))
            await pipe.execute()

    async def get_session(self, session_id: UUID) -> dict | None:
        data = await self._redis.hgetall(self._session_key(session_id))
        if not data:
            return None
        # redis returns bytes; decode
        return {k.decode(): v.decode() for k, v in data.items()}

    async def is_access_jti_valid(self, jti: str) -> bool:
        return bool(await self._redis.exists(self._access_key(jti)))

    async def get_session_by_refresh_token(self, refresh_token: str) -> dict | None:
        raw = await self._redis.get(self._refresh_key(refresh_token))
        if raw is None:
            return None
        if isinstance(raw, bytes):
            raw = raw.decode()
        user_id_str, session_id_str = raw.split(":", 1)
        return {"user_id": user_id_str, "session_id": session_id_str}

    async def rotate_session(
        self,
        session_id: UUID,
        old_refresh_token: str,
        new_access_jti: str,
        new_refresh_token: str,
        access_ttl: int,
        refresh_ttl: int,
    ) -> None:
        # First, read the session to get user_id and old jti
        session_data = await self.get_session(session_id)
        if session_data is None:
            return

        user_id = session_data["user_id"]
        old_jti = session_data.get("current_jti", "")
        now_iso = datetime.now(tz=timezone.utc).isoformat()

        async with self._redis.pipeline(transaction=True) as pipe:
            # Remove old refresh token
            pipe.delete(self._refresh_key(old_refresh_token))
            # Remove old access jti
            if old_jti:
                pipe.delete(self._access_key(old_jti))
            # Set new access jti
            pipe.setex(self._access_key(new_access_jti), access_ttl, f"{user_id}:{session_id}")
            # Set new refresh token
            pipe.setex(
                self._refresh_key(new_refresh_token),
                refresh_ttl,
                f"{user_id}:{session_id}",
            )
            # Update session hash
            pipe.hset(
                self._session_key(session_id),
                mapping={
                    "last_used": now_iso,
                    "current_jti": new_access_jti,
                    "current_refresh": new_refresh_token,
                },
            )
            pipe.expire(self._session_key(session_id), refresh_ttl)
            await pipe.execute()

    async def revoke_session(self, session_id: UUID) -> None:
        session_data = await self.get_session(session_id)
        if session_data is None:
            return

        user_id = session_data.get("user_id", "")
        jti = session_data.get("current_jti", "")
        refresh = session_data.get("current_refresh", "")

        async with self._redis.pipeline(transaction=True) as pipe:
            if jti:
                pipe.delete(self._access_key(jti))
            if refresh:
                pipe.delete(self._refresh_key(refresh))
            pipe.delete(self._session_key(session_id))
            if user_id:
                pipe.srem(self._user_sessions_key(user_id), str(session_id))
            await pipe.execute()

    async def revoke_all_user_sessions(self, user_id: UUID) -> None:
        session_ids_raw = await self._redis.smembers(self._user_sessions_key(user_id))
        for sid_bytes in session_ids_raw:
            sid_str = sid_bytes.decode() if isinstance(sid_bytes, bytes) else sid_bytes
            await self.revoke_session(UUID(sid_str))
        await self._redis.delete(self._user_sessions_key(user_id))

import secrets
import uuid
from datetime import datetime, timezone, timedelta
from uuid import UUID

import jwt

from auth_service.application.ports.token_service import TokenService
from auth_service.domain.exceptions import TokenExpiredError, InvalidTokenError

_ALGORITHM = "HS256"


class JwtTokenService(TokenService):
    def __init__(self, secret: str, access_token_expire_minutes: int = 15) -> None:
        self._secret = secret
        self._access_ttl_minutes = access_token_expire_minutes

    def generate_access_token(self, user_id: UUID, session_id: UUID) -> str:
        now = datetime.now(tz=timezone.utc)
        payload = {
            "sub": str(user_id),
            "sid": str(session_id),
            "jti": str(uuid.uuid4()),
            "iat": now,
            "exp": now + timedelta(minutes=self._access_ttl_minutes),
        }
        return jwt.encode(payload, self._secret, algorithm=_ALGORITHM)

    def generate_refresh_token(self) -> str:
        return secrets.token_urlsafe(32)

    def decode_access_token(self, token: str) -> dict:
        try:
            return jwt.decode(token, self._secret, algorithms=[_ALGORITHM])
        except jwt.ExpiredSignatureError as exc:
            raise TokenExpiredError("Access token has expired") from exc
        except jwt.PyJWTError as exc:
            raise InvalidTokenError("Invalid access token") from exc

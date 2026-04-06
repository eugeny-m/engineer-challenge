import secrets
import uuid
from datetime import datetime, timezone, timedelta
from uuid import UUID

import jwt

from auth_service.application.ports.token_service import TokenService
from auth_service.domain.exceptions import TokenExpiredError, InvalidTokenError
from auth_service.infrastructure.logging import get_logger

_ALGORITHM = "HS256"
_log = get_logger(__name__)


class JwtTokenService(TokenService):
    def __init__(self, secret: str, access_token_expire_minutes: int = 15) -> None:
        self._secret = secret
        self._access_ttl_minutes = access_token_expire_minutes

    def generate_access_token(self, user_id: UUID, session_id: UUID) -> tuple[str, str]:
        now = datetime.now(tz=timezone.utc)
        jti = str(uuid.uuid4())
        payload = {
            "sub": str(user_id),
            "sid": str(session_id),
            "jti": jti,
            "iat": now,
            "exp": now + timedelta(minutes=self._access_ttl_minutes),
        }
        token = jwt.encode(payload, self._secret, algorithm=_ALGORITHM)
        _log.debug(
            "jwt.generate_access_token",
            user_id=str(user_id),
            session_id=str(session_id),
            jti=jti,
        )
        return token, jti

    def generate_refresh_token(self) -> str:
        return secrets.token_urlsafe(32)

    def decode_access_token(self, token: str) -> dict:
        try:
            claims = jwt.decode(token, self._secret, algorithms=[_ALGORITHM])
            _log.debug("jwt.decode_access_token.success", jti=claims.get("jti"))
            return claims
        except jwt.ExpiredSignatureError as exc:
            _log.warning("jwt.decode_access_token.expired")
            raise TokenExpiredError("Access token has expired") from exc
        except jwt.PyJWTError as exc:
            _log.warning("jwt.decode_access_token.invalid", error=str(exc))
            raise InvalidTokenError("Invalid access token") from exc

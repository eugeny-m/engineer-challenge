from abc import ABC, abstractmethod
from uuid import UUID


class TokenService(ABC):
    @abstractmethod
    def generate_access_token(self, user_id: UUID, session_id: UUID) -> str:
        """Generate a signed JWT with sub (user_id), jti (UUID4), sid (session_id), iat, exp claims."""
        ...

    @abstractmethod
    def generate_refresh_token(self) -> str:
        """Generate an opaque URL-safe random refresh token string."""
        ...

    @abstractmethod
    def decode_access_token(self, token: str) -> dict:
        """Decode and verify an access JWT, returning the claims dict.

        Raises TokenExpiredError if expired, InvalidTokenError if invalid.
        """
        ...

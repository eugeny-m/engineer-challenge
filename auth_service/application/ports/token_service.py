from abc import ABC, abstractmethod
from uuid import UUID


class TokenService(ABC):
    @abstractmethod
    def generate_access_token(self, user_id: UUID, session_id: UUID) -> tuple[str, str]:
        """Generate a signed JWT; return (token, jti).

        The jti is a UUID4 string embedded in the token claims.  Returning it
        directly avoids a redundant decode by callers that need the jti for
        session storage.
        """
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

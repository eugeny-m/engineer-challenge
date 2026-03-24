import uuid

from auth_service.application.dto import AuthenticateUserCommand, TokenPairDTO
from auth_service.application.ports.password_hasher import PasswordHasher
from auth_service.application.ports.token_service import TokenService
from auth_service.application.ports.token_store import TokenStore
from auth_service.domain.exceptions import InvalidCredentialsError, UserNotFoundError
from auth_service.domain.repositories.user_repository import UserRepository
from auth_service.domain.value_objects.email import Email

# TTL constants (seconds)
ACCESS_TOKEN_TTL = 15 * 60       # 15 minutes
REFRESH_TOKEN_TTL = 30 * 24 * 3600  # 30 days


class AuthenticateUserHandler:
    def __init__(
        self,
        user_repo: UserRepository,
        hasher: PasswordHasher,
        token_service: TokenService,
        token_store: TokenStore,
    ) -> None:
        self._user_repo = user_repo
        self._hasher = hasher
        self._token_service = token_service
        self._token_store = token_store

    async def handle(self, command: AuthenticateUserCommand) -> TokenPairDTO:
        email = Email(command.email)
        user = await self._user_repo.find_by_email(email)
        if user is None:
            raise InvalidCredentialsError("Invalid email or password")

        if not self._hasher.verify(command.password, user.hashed_password.value):
            raise InvalidCredentialsError("Invalid email or password")

        session_id = uuid.uuid4()
        access_token = self._token_service.generate_access_token(user.id, session_id)
        refresh_token = self._token_service.generate_refresh_token()

        # Extract jti from access token claims
        claims = self._token_service.decode_access_token(access_token)
        jti = claims["jti"]

        await self._token_store.create_session(
            session_id=session_id,
            user_id=user.id,
            access_jti=jti,
            refresh_token=refresh_token,
            device_info=command.device_info,
            access_ttl=ACCESS_TOKEN_TTL,
            refresh_ttl=REFRESH_TOKEN_TTL,
        )

        return TokenPairDTO(
            access_token=access_token,
            refresh_token=refresh_token,
            session_id=session_id,
        )

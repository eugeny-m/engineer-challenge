from auth_service.application.dto import RevokeSessionCommand
from auth_service.application.ports.token_store import TokenStore


class RevokeSessionHandler:
    def __init__(self, token_store: TokenStore) -> None:
        self._token_store = token_store

    async def handle(self, command: RevokeSessionCommand) -> None:
        await self._token_store.revoke_session(command.session_id)

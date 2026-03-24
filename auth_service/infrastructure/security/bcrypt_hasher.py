import bcrypt

from auth_service.application.ports.password_hasher import PasswordHasher

_ROUNDS = 12


class BcryptHasher(PasswordHasher):
    def hash(self, plain_password: str) -> str:
        salt = bcrypt.gensalt(rounds=_ROUNDS)
        hashed = bcrypt.hashpw(plain_password.encode(), salt)
        return hashed.decode()

    def verify(self, plain_password: str, hashed_password: str) -> bool:
        try:
            return bcrypt.checkpw(plain_password.encode(), hashed_password.encode())
        except Exception:
            return False

from abc import ABC, abstractmethod


class PasswordHasher(ABC):
    @abstractmethod
    def hash(self, plain_password: str) -> str: ...

    @abstractmethod
    def verify(self, plain_password: str, hashed_password: str) -> bool: ...

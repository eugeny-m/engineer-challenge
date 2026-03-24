from dataclasses import dataclass

from auth_service.domain.exceptions import WeakPasswordError

_MIN_LENGTH = 8


@dataclass(frozen=True)
class PlainPassword:
    value: str

    def __post_init__(self) -> None:
        if len(self.value) < _MIN_LENGTH:
            raise WeakPasswordError(
                f"Password must be at least {_MIN_LENGTH} characters long."
            )
        if not any(ch.isdigit() for ch in self.value):
            raise WeakPasswordError("Password must contain at least one digit.")

    def __str__(self) -> str:
        return "***"

    def __repr__(self) -> str:
        return "PlainPassword(***)"

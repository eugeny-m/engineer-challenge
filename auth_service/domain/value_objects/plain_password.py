from dataclasses import dataclass

from auth_service.domain.exceptions import WeakPasswordError

_MIN_LENGTH = 8
# bcrypt silently truncates inputs at 72 bytes.  Enforce the limit explicitly
# so that two passwords differing only after byte 72 are rejected rather than
# treated as identical.
_MAX_BYTES = 72


@dataclass(frozen=True)
class PlainPassword:
    value: str

    def __post_init__(self) -> None:
        if len(self.value) < _MIN_LENGTH:
            raise WeakPasswordError(
                f"Password must be at least {_MIN_LENGTH} characters long."
            )
        if len(self.value.encode("utf-8")) > _MAX_BYTES:
            raise WeakPasswordError(
                f"Password must be at most {_MAX_BYTES} bytes when UTF-8 encoded."
            )
        if not any(ch.isdigit() for ch in self.value):
            raise WeakPasswordError("Password must contain at least one digit.")

    def __str__(self) -> str:
        return "***"

    def __repr__(self) -> str:
        return "PlainPassword(***)"

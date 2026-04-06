from dataclasses import dataclass


@dataclass(frozen=True)
class ResetToken:
    value: str

    def __str__(self) -> str:
        return self.value

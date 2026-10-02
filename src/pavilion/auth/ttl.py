"""Token lifetimes, written the way people type them: "30m", "3h", "7d"."""

import re
from dataclasses import dataclass
from datetime import timedelta

UNITS = {"s": "seconds", "m": "minutes", "h": "hours", "d": "days"}
_PATTERN = re.compile(r"(\d+)\s*([smhd]?)")


@dataclass(frozen=True)
class TTL:
    amount: int
    unit: str  # a value of UNITS, i.e. a timedelta keyword

    @classmethod
    def parse(cls, text: str) -> "TTL":
        """Parse "30m", "3h", "7d" or "90s"; a bare number means hours."""
        match = _PATTERN.fullmatch(text.strip().lower())
        if not match or int(match[1]) == 0:
            raise ValueError(f"Invalid duration {text!r}: use e.g. 30m, 3h or 7d")
        return cls(int(match[1]), UNITS[match[2] or "h"])

    @property
    def timedelta(self) -> timedelta:
        return timedelta(**{self.unit: self.amount})

    def python(self) -> str:
        """Source code for this TTL, keeping the unit it was written in."""
        return f"timedelta({self.unit}={self.amount})"

    def __str__(self) -> str:
        return f"{self.amount}{self.unit[0]}"


DEFAULT_ACCESS_TTL = TTL(3, "hours")
DEFAULT_REFRESH_TTL = TTL(24, "hours")


def validate_ttls(access: TTL, refresh: TTL) -> None:
    if refresh.timedelta <= access.timedelta:
        raise ValueError(
            f"Refresh token TTL ({refresh}) must be longer than the access token TTL ({access})"
        )

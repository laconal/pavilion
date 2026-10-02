"""The choices behind a generated auth package."""

from dataclasses import dataclass
from enum import StrEnum

from pavilion.auth.ttl import DEFAULT_ACCESS_TTL, DEFAULT_REFRESH_TTL, TTL
from pavilion.keys.generate import Algorithm

SYMMETRIC_ALGORITHM = "HS256"


class Transport(StrEnum):
    """How the access/refresh tokens travel between client and server."""

    HEADER = "header"
    COOKIE = "cookie"

class Strategy(StrEnum):
    ASYMMETRIC = "asymmetric"
    SYMMETRIC = "symmetric"

class Hashing(StrEnum):
    ARGON2 = "argon2"
    BCRYPT = "bcrypt"

class RefreshKeys(StrEnum):
    SHARED = "shared"
    SEPARATE = "separate"

# Output file name -> template path (relative to auth/templates), for every transport.
COMMON_TEMPLATES = {
    "__init__.py": "__init__.py.jinja",
    "passwords.py": "passwords.py.jinja",
    "tokens.py": "tokens.py.jinja",
    "service.py": "service.py.jinja",
}
COOKIE_TEMPLATES = {"cookies.py": "cookies.py.jinja"}
# Every file pavilion may generate, so `--force` can remove ones a new config doesn't use.
ALL_OUTPUT_FILES = frozenset(COMMON_TEMPLATES) | frozenset(COOKIE_TEMPLATES)

@dataclass(frozen=True)
class AuthConfig:
    transport: Transport
    strategy: Strategy
    hashing: Hashing
    algorithm: Algorithm | None = None  # asymmetric only
    refresh_keys: RefreshKeys = RefreshKeys.SHARED
    access_ttl: TTL = DEFAULT_ACCESS_TTL
    refresh_ttl: TTL = DEFAULT_REFRESH_TTL

    @property
    def separate_refresh_keys(self) -> bool:
        return self.refresh_keys is RefreshKeys.SEPARATE

    @property
    def jwt_algorithm(self) -> str:
        return str(self.algorithm) if self.strategy is Strategy.ASYMMETRIC else SYMMETRIC_ALGORITHM

    @property
    def templates(self) -> dict[str, str]:
        """Output file name -> template path (relative to auth/templates)."""
        if self.transport is Transport.COOKIE:
            return COMMON_TEMPLATES | COOKIE_TEMPLATES
        return COMMON_TEMPLATES

    @property
    def dependencies(self) -> list[str]:
        # Asymmetric algorithms need PyJWT's `cryptography` extra.
        jwt = "pyjwt[crypto]" if self.strategy is Strategy.ASYMMETRIC else "pyjwt"
        return [jwt, "argon2-cffi" if self.hashing is Hashing.ARGON2 else "bcrypt"]

    def describe(self) -> str:
        hashing = "Argon2" if self.hashing is Hashing.ARGON2 else "bcrypt"
        via = "cookies" if self.transport is Transport.COOKIE else "header"
        refresh = ", separate refresh keys" if self.separate_refresh_keys else ""
        ttls = f"access {self.access_ttl} / refresh {self.refresh_ttl}"
        return f"JWT {self.jwt_algorithm} via {via} ({self.strategy}{refresh}), {ttls}, {hashing}"

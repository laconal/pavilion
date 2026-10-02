"""Generating signing keys and secrets (e.g. for JWTs)."""

import os
import secrets
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec, ed25519, rsa

DEFAULT_SECRETS_DIR = Path("secrets")
SECRET_NAME = "jwt_secret"
# Refresh-token keys sit next to the access ones: private_refresh.pem, jwt_secret_refresh.
REFRESH_SUFFIX = "_refresh"
DEFAULT_RSA_KEY_SIZE = 2048
# Below 2048 is no longer considered secure; above 16384 generation takes minutes.
MIN_RSA_KEY_SIZE = 2048
MAX_RSA_KEY_SIZE = 16384

# Ignores everything in the secrets directory except this file itself.
GITIGNORE = "*\n!.gitignore\n"


class Algorithm(StrEnum):
    """JWT (JWA) algorithm names."""

    RS256 = "RS256"
    ES256 = "ES256"
    EdDSA = "EdDSA"


DESCRIPTIONS = {
    Algorithm.RS256: "RSA, SHA-256",
    Algorithm.ES256: "ECDSA P-256, SHA-256",
    Algorithm.EdDSA: "Ed25519",
}


@dataclass(frozen=True)
class KeyPair:
    """Where a PEM key pair lives."""

    private: Path
    public: Path

    @classmethod
    def in_dir(cls, directory: Path, *, refresh: bool = False) -> "KeyPair":
        suffix = REFRESH_SUFFIX if refresh else ""
        return cls(directory / f"private{suffix}.pem", directory / f"public{suffix}.pem")

    @property
    def directory(self) -> Path:
        return self.private.parent

    def existing(self) -> list[Path]:
        return [p for p in (self.private, self.public) if p.exists()]


def secret_path(directory: Path, *, refresh: bool = False) -> Path:
    return directory / (SECRET_NAME + (REFRESH_SUFFIX if refresh else ""))


class KeysExistError(Exception):
    def __init__(self, paths: list[Path]):
        super().__init__(", ".join(map(str, paths)))
        self.paths = paths


class KeyMismatchError(Exception):
    def __init__(self, message: str, keys: KeyPair):
        super().__init__(message)
        self.keys = keys


def validate_rsa_key_size(bits: int) -> None:
    if not MIN_RSA_KEY_SIZE <= bits <= MAX_RSA_KEY_SIZE:
        raise ValueError(f"RSA key size must be {MIN_RSA_KEY_SIZE}-{MAX_RSA_KEY_SIZE} bits")


def _generate_private_key(algorithm: Algorithm, rsa_key_size: int):
    match algorithm:
        case Algorithm.RS256:
            validate_rsa_key_size(rsa_key_size)
            return rsa.generate_private_key(public_exponent=65537, key_size=rsa_key_size)
        case Algorithm.ES256:
            return ec.generate_private_key(ec.SECP256R1())
        case Algorithm.EdDSA:
            return ed25519.Ed25519PrivateKey.generate()


def _write(path: Path, data: bytes, mode: int) -> None:
    # Create with the final mode so the file is never briefly world-readable.
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, mode)
    with os.fdopen(fd, "wb") as f:
        f.write(data)
    os.chmod(path, mode)  # O_CREAT's mode doesn't apply when overwriting


def _prepare_directory(directory: Path) -> None:
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    gitignore = directory / ".gitignore"
    if not gitignore.exists():
        gitignore.write_text(GITIGNORE)


def read_rsa_key_size(private_key_path: Path) -> int | None:
    key = serialization.load_pem_private_key(private_key_path.read_bytes(), password=None)
    return key.key_size if isinstance(key, rsa.RSAPrivateKey) else None


def detect_algorithm(private_key_path: Path) -> Algorithm | None:
    """Which supported algorithm a PEM private key is for, if any."""
    key = serialization.load_pem_private_key(private_key_path.read_bytes(), password=None)
    if isinstance(key, rsa.RSAPrivateKey):
        return Algorithm.RS256
    if isinstance(key, ec.EllipticCurvePrivateKey) and isinstance(key.curve, ec.SECP256R1):
        return Algorithm.ES256
    if isinstance(key, ed25519.Ed25519PrivateKey):
        return Algorithm.EdDSA
    return None


def check_keys(keys: KeyPair, algorithm: Algorithm, rsa_key_size: int | None = None) -> bool:
    """Whether `keys` exist and are usable; False if neither file exists.

    Raises KeyMismatchError if the existing keys are incomplete or don't match
    `algorithm` (or `rsa_key_size`, when given).
    """
    existing = keys.existing()
    if not existing:
        return False
    if len(existing) == 1:
        raise KeyMismatchError(f"Incomplete key pair: {keys.private}, {keys.public}", keys)
    actual = detect_algorithm(keys.private)
    if actual != algorithm:
        raise KeyMismatchError(
            f"Key in {keys.private} is {actual or 'unsupported'}, but {algorithm} was selected",
            keys,
        )
    if rsa_key_size is not None and (bits := read_rsa_key_size(keys.private)) != rsa_key_size:
        raise KeyMismatchError(
            f"Key in {keys.private} is {bits}-bit, but {rsa_key_size}-bit was selected", keys
        )
    return True


def ensure_keys(keys: KeyPair, algorithm: Algorithm, rsa_key_size: int | None = None) -> bool:
    """Generate a key pair unless a matching one exists; returns True if generated.

    `rsa_key_size` defaults to DEFAULT_RSA_KEY_SIZE for new keys; when given, existing
    RS256 keys must also have that size.
    """
    if check_keys(keys, algorithm, rsa_key_size):
        return False
    generate_keys(keys, algorithm, rsa_key_size=rsa_key_size or DEFAULT_RSA_KEY_SIZE)
    return True


def ensure_secret(path: Path) -> bool:
    """Generate an HMAC secret at `path` unless one exists; returns True if generated."""
    if path.exists():
        return False
    _prepare_directory(path.parent)
    _write(path, (secrets.token_urlsafe(64) + "\n").encode(), 0o600)
    return True


def generate_keys(
    keys: KeyPair,
    algorithm: Algorithm,
    *,
    rsa_key_size: int = DEFAULT_RSA_KEY_SIZE,
    force: bool = False,
) -> KeyPair:
    """Write a PEM key pair to `keys`' paths and return them.

    `rsa_key_size` only applies to RS256.
    """
    existing = keys.existing()
    if existing and not force:
        raise KeysExistError(existing)

    private_key = _generate_private_key(algorithm, rsa_key_size)
    _prepare_directory(keys.directory)
    private_pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    public_pem = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    _write(keys.private, private_pem, 0o600)
    _write(keys.public, public_pem, 0o644)
    return keys

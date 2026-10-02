"""Rendering an auth package (tokens, cookies, password hashing, login/refresh/logout)."""

from dataclasses import dataclass
from pathlib import Path

from jinja2 import Environment, PackageLoader, StrictUndefined

from pavilion.auth.config import ALL_OUTPUT_FILES, AuthConfig, Strategy, Transport
from pavilion.keys.generate import (
    Algorithm,
    KeyPair,
    check_keys,
    ensure_keys,
    ensure_secret,
    read_rsa_key_size,
    secret_path,
)


class AuthFilesExistError(Exception):
    def __init__(self, paths: list[Path]):
        super().__init__(", ".join(map(str, paths)))
        self.paths = paths


@dataclass(frozen=True)
class AuthResult:
    files: list[Path]
    # Files from a previous run that this config doesn't use (deleted with --force).
    removed: list[Path]
    # Human-readable notes about the keys/secrets used: access first, then refresh.
    secrets_notes: list[str]


_env = Environment(
    loader=PackageLoader("pavilion.auth", "templates"),
    undefined=StrictUndefined,
    trim_blocks=True,
    lstrip_blocks=True,
    keep_trailing_newline=True,
)


def key_pairs(secrets_dir: Path, separate_refresh_keys: bool) -> list[KeyPair]:
    """Asymmetric key pairs used: access tokens first, then refresh tokens if separate."""
    access = KeyPair.in_dir(secrets_dir)
    if separate_refresh_keys:
        return [access, KeyPair.in_dir(secrets_dir, refresh=True)]
    return [access]


def _prepare_secrets(
    config: AuthConfig, secrets_dir: Path, rsa_key_size: int | None
) -> list[str]:
    def verb(created: bool) -> str:
        return "Generated" if created else "Using existing"

    if config.strategy is Strategy.SYMMETRIC:
        paths = [secret_path(secrets_dir)]
        if config.separate_refresh_keys:
            paths.append(secret_path(secrets_dir, refresh=True))
        return [f"{verb(ensure_secret(path))} HS256 secret: {path}" for path in paths]

    assert config.algorithm is not None
    pairs = key_pairs(secrets_dir, config.separate_refresh_keys)
    # Validate every pair first so a mismatch in one doesn't leave new keys behind.
    for keys in pairs:
        check_keys(keys, config.algorithm, rsa_key_size)
    notes = []
    for keys in pairs:
        created = ensure_keys(keys, config.algorithm, rsa_key_size)
        label = str(config.algorithm)
        if config.algorithm is Algorithm.RS256:
            label += f" ({read_rsa_key_size(keys.private)}-bit)"
        notes.append(f"{verb(created)} {label} key pair: {keys.private}, {keys.public}")
    return notes


def scaffold_auth(
    config: AuthConfig,
    directory: Path,
    secrets_dir: Path,
    *,
    rsa_key_size: int | None = None,
    force: bool = False,
) -> AuthResult:
    """Render the auth package into `directory` and make sure signing material exists.

    `rsa_key_size` applies to newly generated RS256 keys (default 2048); when given,
    existing RS256 keys must match it.

    Raises AuthFilesExistError or KeyMismatchError before writing anything.
    """
    targets = {directory / name: template for name, template in config.templates.items()}
    existing = sorted(p for name in ALL_OUTPUT_FILES if (p := directory / name).exists())
    if existing and not force:
        raise AuthFilesExistError(existing)
    stale = [path for path in existing if path not in targets]

    secrets_notes = _prepare_secrets(config, secrets_dir, rsa_key_size)

    context = {
        "cookie": config.transport is Transport.COOKIE,
        "hashing": str(config.hashing),
        "asymmetric": config.strategy is Strategy.ASYMMETRIC,
        "algorithm": config.jwt_algorithm,
        "separate_refresh_keys": config.separate_refresh_keys,
        "access_ttl": config.access_ttl.python(),
        "refresh_ttl": config.refresh_ttl.python(),
        "access_keys": KeyPair.in_dir(secrets_dir),
        "refresh_keys": KeyPair.in_dir(secrets_dir, refresh=True),
        "access_secret": secret_path(secrets_dir).as_posix(),
        "refresh_secret": secret_path(secrets_dir, refresh=True).as_posix(),
        "package": directory.name,
    }
    directory.mkdir(parents=True, exist_ok=True)
    for path, template in targets.items():
        path.write_text(_env.get_template(template).render(context))
    for path in stale:
        path.unlink()
    return AuthResult(files=list(targets), removed=stale, secrets_notes=secrets_notes)

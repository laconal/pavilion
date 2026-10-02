"""`pavilion add auth`"""

from pathlib import Path
from typing import Annotated

import typer

from pavilion import ui
from pavilion.auth.config import AuthConfig, Hashing, RefreshKeys, Strategy, Transport
from pavilion.auth.scaffold import AuthFilesExistError, key_pairs, scaffold_auth
from pavilion.auth.ttl import DEFAULT_ACCESS_TTL, DEFAULT_REFRESH_TTL, TTL, validate_ttls
from pavilion.keys.cli import RsaBitsOption, check_rsa_bits, choose_algorithm, choose_rsa_bits
from pavilion.keys.generate import (
    DEFAULT_SECRETS_DIR,
    Algorithm,
    KeyMismatchError,
    KeyPair,
)

REFRESH_KEY_LABELS = {
    Strategy.ASYMMETRIC: "Separate key pair  (a leaked access key can't forge refresh tokens)",
    Strategy.SYMMETRIC: "Separate secret    (a leaked access secret can't forge refresh tokens)",
}



def _parse_ttl(text: str) -> TTL:
    try:
        return TTL.parse(text)
    except ValueError as e:
        raise typer.BadParameter(str(e)) from None


def _ttl_option(flag: str, default: TTL, token: str) -> typer.models.OptionInfo:
    return typer.Option(
        flag,
        parser=_parse_ttl,
        metavar="DURATION",
        help=f"{token} token lifetime, e.g. 30m, 3h, 7d (default {default}). Prompts if omitted.",
        show_default=False,
    )


def _choose_ttl(message: str, default: TTL, longer_than: TTL | None = None) -> TTL:
    def validate(answer: str) -> bool | str:
        try:
            ttl = TTL.parse(answer)
            if longer_than is not None:
                validate_ttls(longer_than, ttl)
        except ValueError as e:
            return str(e)
        return True

    return TTL.parse(ui.text(message, str(default), validate))


def add_auth(
    transport: Annotated[
        Transport | None,
        typer.Option(help="How tokens travel: Authorization header or cookies.", show_default=False),
    ] = None,
    strategy: Annotated[
        Strategy | None, typer.Option(help="Token signing strategy.", show_default=False)
    ] = None,
    algorithm: Annotated[
        Algorithm | None,
        typer.Option(
            case_sensitive=False, help="Asymmetric JWT algorithm.", show_default=False
        ),
    ] = None,
    rsa_bits: RsaBitsOption = None,
    refresh_keys: Annotated[
        RefreshKeys | None,
        typer.Option(help="Sign refresh tokens with their own keys.", show_default=False),
    ] = None,
    access_ttl: Annotated[
        TTL | None, _ttl_option("--access-ttl", DEFAULT_ACCESS_TTL, "Access")
    ] = None,
    refresh_ttl: Annotated[
        TTL | None, _ttl_option("--refresh-ttl", DEFAULT_REFRESH_TTL, "Refresh")
    ] = None,
    hashing: Annotated[
        Hashing | None, typer.Option(help="Password hashing.", show_default=False)
    ] = None,
    directory: Annotated[
        Path, typer.Option("--dir", "-d", help="Directory for the generated package.")
    ] = Path("auth"),
    force: Annotated[
        bool, typer.Option("--force", help="Overwrite existing auth files.")
    ] = False,
) -> None:
    """Generate an auth package: JWT access/refresh tokens, password hashing, login/refresh/logout.

    Prompts for any choice not given as an option.
    """
    transport = transport or ui.select(
        "Authentication transport:",
        {
            Transport.HEADER: "JWT in Authorization header  (Bearer token)",
            Transport.COOKIE: "JWT in cookies               (HttpOnly)",
        },
    )
    strategy = strategy or ui.select(
        "Token/signing strategy:",
        {
            Strategy.ASYMMETRIC: "Asymmetric  (private key signs, public key verifies)",
            Strategy.SYMMETRIC: "Symmetric   (HS256, one shared secret)",
        },
    )
    if strategy is Strategy.SYMMETRIC and algorithm:
        raise typer.BadParameter("only applies to --strategy asymmetric", param_hint="--algorithm")
    if strategy is Strategy.ASYMMETRIC:
        algorithm = algorithm or choose_algorithm("Algorithm:", default=Algorithm.EdDSA)
    check_rsa_bits(rsa_bits, algorithm)
    refresh_keys = refresh_keys or ui.select(
        "Refresh token keys:",
        {
            RefreshKeys.SHARED: "Same as access tokens",
            RefreshKeys.SEPARATE: REFRESH_KEY_LABELS[strategy],
        },
    )
    if algorithm is Algorithm.RS256 and rsa_bits is None:
        # Existing keys get reused, so only ask for a size when new ones will be made.
        separate = refresh_keys is RefreshKeys.SEPARATE
        if any(not keys.private.exists() for keys in key_pairs(DEFAULT_SECRETS_DIR, separate)):
            rsa_bits = choose_rsa_bits()
    access_ttl = access_ttl or _choose_ttl("Access token TTL:", DEFAULT_ACCESS_TTL)
    refresh_ttl = refresh_ttl or _choose_ttl(
        "Refresh token TTL:", DEFAULT_REFRESH_TTL, longer_than=access_ttl
    )
    try:
        validate_ttls(access_ttl, refresh_ttl)
    except ValueError as e:
        raise typer.BadParameter(str(e), param_hint="--access-ttl/--refresh-ttl") from None
    hashing = hashing or ui.select(
        "Password hashing:", {Hashing.ARGON2: "Argon2", Hashing.BCRYPT: "bcrypt"}
    )

    config = AuthConfig(
        transport=transport,
        hashing=hashing,
        strategy=strategy,
        algorithm=algorithm,
        refresh_keys=refresh_keys,
        access_ttl=access_ttl,
        refresh_ttl=refresh_ttl,
    )
    try:
        result = scaffold_auth(
            config, directory, DEFAULT_SECRETS_DIR, rsa_key_size=rsa_bits, force=force
        )
    except AuthFilesExistError as e:
        raise ui.fail(
            f"Auth files already exist: {', '.join(map(str, e.paths))}. Use --force to overwrite."
        )
    except KeyMismatchError as e:
        size = f" --rsa-bits {rsa_bits}" if rsa_bits else ""
        target = " --refresh" if e.keys == KeyPair.in_dir(DEFAULT_SECRETS_DIR, refresh=True) else ""
        raise ui.fail(
            f"{e}.\nPick a matching option, or replace the keys with "
            f"`pavilion add keys {algorithm}{size}{target} --force`.",
            color=typer.colors.RED,
        )

    typer.secho(f"Generated {directory}/ ({config.describe()}):", fg=typer.colors.GREEN)
    for path in result.files:
        typer.echo(f"  {path}")
    for path in result.removed:
        typer.echo(f"  {path} (removed, not used by this configuration)")
    for note in result.secrets_notes:
        typer.echo(note)
    deps = " ".join(f"'{d}'" if "[" in d else d for d in config.dependencies)
    typer.echo(f"\nNext: uv add {deps}")

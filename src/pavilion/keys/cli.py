"""`pavilion add keys`, plus the algorithm/RSA prompts `add auth` reuses."""

from pathlib import Path
from typing import Annotated

import typer

from pavilion import ui
from pavilion.keys.generate import (
    DEFAULT_RSA_KEY_SIZE,
    DEFAULT_SECRETS_DIR,
    DESCRIPTIONS,
    MAX_RSA_KEY_SIZE,
    MIN_RSA_KEY_SIZE,
    Algorithm,
    KeyPair,
    generate_keys,
    validate_rsa_key_size,
)

RsaBitsOption = Annotated[
    int | None,
    typer.Option(
        "--rsa-bits",
        min=MIN_RSA_KEY_SIZE,
        max=MAX_RSA_KEY_SIZE,
        help=f"RSA key size for RS256 (default {DEFAULT_RSA_KEY_SIZE}). Prompts if omitted.",
        show_default=False,
    ),
]


def choose_algorithm(message: str, default: Algorithm | None = None) -> Algorithm:
    return ui.select(
        message, {alg: f"{alg:<6} ({DESCRIPTIONS[alg]})" for alg in Algorithm}, default
    )


def choose_rsa_bits() -> int:
    def validate(answer: str) -> bool | str:
        try:
            validate_rsa_key_size(int(answer))
        except ValueError:
            return f"Enter a number from {MIN_RSA_KEY_SIZE} to {MAX_RSA_KEY_SIZE}"
        return True

    return int(ui.text("RSA key size (bits):", str(DEFAULT_RSA_KEY_SIZE), validate))


def check_rsa_bits(rsa_bits: int | None, algorithm: Algorithm | None) -> None:
    if rsa_bits is not None and algorithm is not Algorithm.RS256:
        raise typer.BadParameter("only applies to RS256", param_hint="--rsa-bits")


def add_keys(
    algorithm: Annotated[
        Algorithm | None,
        typer.Argument(
            case_sensitive=False,
            help="Signing algorithm. Prompts interactively if omitted.",
            show_default=False,
        ),
    ] = None,
    rsa_bits: RsaBitsOption = None,
    directory: Annotated[
        Path, typer.Option("--dir", "-d", help="Directory to write the keys to.")
    ] = DEFAULT_SECRETS_DIR,
    refresh: Annotated[
        bool,
        typer.Option(
            "--refresh",
            help="Write the refresh-token pair (private_refresh.pem, public_refresh.pem).",
        ),
    ] = False,
    force: Annotated[
        bool, typer.Option("--force", help="Overwrite existing keys.")
    ] = False,
) -> None:
    """Generate a public/private key pair (PEM) in ./secrets."""
    keys = KeyPair.in_dir(directory, refresh=refresh)
    # Check before prompting so we don't ask questions we can't act on.
    if not force and (existing := keys.existing()):
        raise ui.fail(
            f"Keys already exist: {', '.join(map(str, existing))}. Use --force to overwrite."
        )

    algorithm = algorithm or choose_algorithm("Which algorithm?")
    check_rsa_bits(rsa_bits, algorithm)
    if algorithm is Algorithm.RS256 and rsa_bits is None:
        rsa_bits = choose_rsa_bits()

    generate_keys(keys, algorithm, rsa_key_size=rsa_bits or DEFAULT_RSA_KEY_SIZE, force=force)
    label = f"{algorithm} ({rsa_bits}-bit)" if algorithm is Algorithm.RS256 else algorithm
    typer.secho(f"Generated {label} key pair:", fg=typer.colors.GREEN)
    typer.echo(f"  private: {keys.private}")
    typer.echo(f"  public:  {keys.public}")

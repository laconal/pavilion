"""Shared terminal interaction: arrow-key menus, text prompts and error exits.

Prompts fall back to their default when there's no terminal (CI, pipes, tests),
since there's nobody to ask.
"""

import sys
from typing import Callable

import questionary
import typer


def interactive() -> bool:
    return sys.stdin.isatty()


def select[T](message: str, options: dict[T, str], default: T | None = None) -> T:
    """Arrow-key menu over `options` (value -> label); defaults to the first one."""
    if default is None:
        default = next(iter(options))
    if not interactive():
        return default

    choices = [questionary.Choice(title=label, value=value) for value, label in options.items()]
    default_choice = next(c for c in choices if c.value == default)
    answer = questionary.select(message, choices=choices, default=default_choice).ask()
    if answer is None:  # Ctrl+C / Esc
        raise typer.Abort()
    return answer


def text(message: str, default: str, validate: Callable[[str], bool | str]) -> str:
    """Free-text prompt; `validate` returns True or an error message to show."""
    if not interactive():
        return default

    answer = questionary.text(message, default=default, validate=validate).ask()
    if answer is None:  # Ctrl+C / Esc
        raise typer.Abort()
    return answer


def fail(message: str, color: str = typer.colors.YELLOW) -> typer.Exit:
    """Print `message` to stderr and return an exit to raise: `raise ui.fail(...)`."""
    typer.secho(message, fg=color, err=True)
    return typer.Exit(1)

"""Adding packages to the project pavilion runs in, with `uv add`."""

import re
import shutil
import subprocess
import tomllib
from enum import Enum, auto
from pathlib import Path

import typer

from pavilion import ui


class DependencyStatus(Enum):
    ALREADY_PRESENT = auto()
    ADDED = auto()
    NO_PROJECT = auto()  # no pyproject.toml in this directory or its parents
    NO_UV = auto()
    FAILED = auto()


def _normalize(name: str) -> str:
    # PEP 503: "SQLAlchemy", "sqlalchemy" and "sql_alchemy"-style spellings compare equal.
    return re.sub(r"[-_.]+", "-", name).lower()


def find_pyproject(start: Path) -> Path | None:
    for directory in (start, *start.parents):
        if (candidate := directory / "pyproject.toml").is_file():
            return candidate
    return None


def project_root(start: Path) -> Path:
    """The directory of the nearest pyproject.toml, or `start` if there is none."""
    pyproject = find_pyproject(start)
    return pyproject.parent if pyproject else start


def declared_dependencies(pyproject: Path) -> set[str]:
    """Normalized names of the runtime dependencies in `[project] dependencies`."""
    data = tomllib.loads(pyproject.read_text())
    names = set()
    for requirement in data.get("project", {}).get("dependencies", []):
        # "SQLAlchemy[asyncio]>=2.0" -> "sqlalchemy"
        if match := re.match(r"\s*([A-Za-z0-9][A-Za-z0-9._-]*)", requirement):
            names.add(_normalize(match[1]))
    return names


# The only two places that touch uv; tests replace them (see tests/conftest.py).
def _find_uv() -> str | None:
    return shutil.which("uv")


def _run(command: list[str], cwd: Path) -> int:
    return subprocess.run(command, cwd=cwd).returncode


def ensure_dependency(package: str, start: Path) -> DependencyStatus:
    """`uv add package` in the project containing `start`, unless it's already declared.

    uv's own output goes straight to the terminal.
    """
    pyproject = find_pyproject(start)
    if pyproject is None:
        return DependencyStatus.NO_PROJECT
    if _normalize(package) in declared_dependencies(pyproject):
        return DependencyStatus.ALREADY_PRESENT
    uv = _find_uv()
    if uv is None:
        return DependencyStatus.NO_UV
    if _run([uv, "add", package], pyproject.parent) == 0:
        return DependencyStatus.ADDED
    return DependencyStatus.FAILED


def install(package: str) -> None:
    """ensure_dependency() for the current directory, reporting the outcome.

    Exits with an error if `uv add` fails; whatever was generated before stays.
    """
    match ensure_dependency(package, Path.cwd()):
        case DependencyStatus.ADDED:
            typer.secho(f"Added {package} to the project.", fg=typer.colors.GREEN)
        case DependencyStatus.ALREADY_PRESENT:
            typer.echo(f"{package} is already a project dependency.")
        case DependencyStatus.NO_PROJECT:
            typer.secho(
                f"No pyproject.toml found; install it yourself: uv add {package}",
                fg=typer.colors.YELLOW,
            )
        case DependencyStatus.NO_UV:
            typer.secho(
                f"uv not found; install it yourself: pip install {package}",
                fg=typer.colors.YELLOW,
            )
        case DependencyStatus.FAILED:
            raise ui.fail(
                f"`uv add {package}` failed (see above); the generated files were kept. "
                "Fix the problem and run it again.",
                color=typer.colors.RED,
            )

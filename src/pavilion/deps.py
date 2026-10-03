"""Adding packages to the project pavilion runs in, with `uv add`."""

import re
import shutil
import subprocess
import tomllib
from enum import Enum, auto
from pathlib import Path


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


def declared_dependencies(pyproject: Path) -> set[str]:
    """Normalized names of the runtime dependencies in `[project] dependencies`."""
    data = tomllib.loads(pyproject.read_text())
    names = set()
    for requirement in data.get("project", {}).get("dependencies", []):
        # "SQLAlchemy[asyncio]>=2.0" -> "sqlalchemy"
        if match := re.match(r"\s*([A-Za-z0-9][A-Za-z0-9._-]*)", requirement):
            names.add(_normalize(match[1]))
    return names


def ensure_dependency(package: str, start: Path) -> DependencyStatus:
    """`uv add package` in the project containing `start`, unless it's already declared.

    uv's own output goes straight to the terminal.
    """
    pyproject = find_pyproject(start)
    if pyproject is None:
        return DependencyStatus.NO_PROJECT
    if _normalize(package) in declared_dependencies(pyproject):
        return DependencyStatus.ALREADY_PRESENT
    uv = shutil.which("uv")
    if uv is None:
        return DependencyStatus.NO_UV
    result = subprocess.run([uv, "add", package], cwd=pyproject.parent)
    return DependencyStatus.ADDED if result.returncode == 0 else DependencyStatus.FAILED

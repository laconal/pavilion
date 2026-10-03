"""Settings in the project's .env file."""

import re
import shutil
import subprocess
from enum import Enum, auto
from pathlib import Path


class EnvStatus(Enum):
    CREATED = auto()  # .env didn't exist
    ADDED = auto()  # appended to an existing .env
    EXISTS = auto()  # already set; left untouched


def ensure_env_var(path: Path, name: str, value: str) -> EnvStatus:
    """Make sure `.env` at `path` defines `name`, without changing an existing value."""
    if not path.exists():
        path.write_text(f"{name}={value}\n")
        return EnvStatus.CREATED
    text = path.read_text()
    if re.search(rf"^\s*(export\s+)?{re.escape(name)}\s*=", text, re.MULTILINE):
        return EnvStatus.EXISTS
    separator = "" if not text or text.endswith("\n") else "\n"
    path.write_text(f"{text}{separator}{name}={value}\n")
    return EnvStatus.ADDED


def is_git_ignored(path: Path) -> bool | None:
    """Whether git ignores `path`; None outside a git repository or without git."""
    git = shutil.which("git")
    if git is None:
        return None
    result = subprocess.run(
        [git, "check-ignore", "-q", path.name], cwd=path.parent, capture_output=True
    )
    return {0: True, 1: False}.get(result.returncode)

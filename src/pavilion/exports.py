"""Keeping a generated package's __init__.py re-exporting what pavilion adds to it."""

import re
from pathlib import Path


_RELATIVE_IMPORT = re.compile(r"from \.(\w+) import (\w+)")


def _insert_sorted(text: str, line: str, module: str) -> str:
    """Insert `line` among the `from .x import y` lines, sorted by module, then name."""
    lines = text.splitlines()
    imports = [i for i, existing in enumerate(lines) if _RELATIVE_IMPORT.match(existing)]
    if not imports:
        # Keep a blank line between a docstring (or other code) and the new import.
        spacer = [""] if lines and lines[-1].strip() else []
        return "\n".join([*lines, *spacer, line]) + "\n"
    key = _RELATIVE_IMPORT.match(line).groups()
    after = [i for i in imports if _RELATIVE_IMPORT.match(lines[i]).groups() > key]
    lines.insert(after[0] if after else imports[-1] + 1, line)
    return "\n".join(lines) + "\n"


def ensure_export(init: Path, module: str, name: str) -> str | None:
    """Add `from .module import name as name` to an existing __init__.py.

    Does nothing if the file already mentions `name`. Returns the added line, if any.
    """
    text = init.read_text()
    if re.search(rf"\b{name}\b", text):
        return None
    line = f"from .{module} import {name} as {name}"
    init.write_text(_insert_sorted(text, line, module))
    return line

"""Rendering standalone utility functions into a `utils` package.

Utilities are grouped into topic modules (tokens.py holds generate_token, generate_code
and hash_token). Each utility's template is a snippet — imports plus definitions — that
merge.py either turns into a new module or merges into the existing one.
"""

from dataclasses import dataclass
from pathlib import Path

from jinja2 import Environment, PackageLoader, StrictUndefined

from pavilion.exports import ensure_export
from pavilion.utils import merge


@dataclass(frozen=True)
class UtilSpec:
    name: str  # function name, also what users type: `pavilion add util generate_password`
    # Topic module (file without .py). Never the function's own name: re-exporting
    # `generate_password` from `generate_password.py` would make the package attribute
    # the function and hide the module (breaking e.g. mock.patch on it).
    module: str
    description: str
    # Other utils (in the same module) this one uses; added first when missing.
    requires: tuple[str, ...] = ()

    @property
    def template(self) -> str:
        return f"{self.name}.py.jinja"


# Docstring of each topic module, written when the module is created.
MODULES = {
    "passwords": "Random passwords.",
    "tokens": "Random tokens and codes, and hashing tokens for storage.",
    "masking": "Hiding most of an email or secret, for logs and hints.",
    "retry": "Retrying flaky operations with exponential backoff.",
    "timing": "Measuring how long code takes.",
    "text": "Text helpers.",
    "dates": "Dates and times.",
}

UTILS: dict[str, UtilSpec] = {
    spec.name: spec
    for spec in [
        UtilSpec("generate_password", "passwords", "random password: letters, digits, symbols"),
        UtilSpec("generate_token", "tokens", "random URL-safe token (reset links, API keys)"),
        UtilSpec("generate_code", "tokens", "random numeric code, e.g. 042917 (verification)"),
        UtilSpec("hash_token", "tokens", "SHA-256 of a token, to store instead of it"),
        UtilSpec("mask_email", "masking", "m***r@gmail.com, for logs and hints"),
        UtilSpec("mask_secret", "masking", "****f3a9: only the last characters of a secret"),
        UtilSpec("retry", "retry", "decorator: retry with exponential backoff (sync/async)"),
        UtilSpec("timer", "timing", "context manager: time a block, log the duration"),
        UtilSpec("timed", "timing", "decorator: log each call's duration (sync/async)", ("timer",)),
        UtilSpec("slugify", "text", "Hello, World! -> hello-world"),
        UtilSpec("utcnow", "dates", "timezone-aware current UTC time"),
    ]
}


class UtilExistsError(Exception):
    def __init__(self, path: Path, name: str):
        super().__init__(f"{name} in {path}")
        self.path = path
        self.name = name


@dataclass(frozen=True)
class UtilResult:
    path: Path
    created_module: bool
    added: list[str]  # utility names written, required ones first
    created_init: bool
    exported: list[str]  # re-export lines added to __init__.py


_env = Environment(
    loader=PackageLoader("pavilion.utils", "templates"),
    undefined=StrictUndefined,
    trim_blocks=True,
    lstrip_blocks=True,
    keep_trailing_newline=True,
)


def _snippet(spec: UtilSpec) -> merge.Snippet:
    return merge.split(_env.get_template(spec.template).render())


def scaffold_util(spec: UtilSpec, directory: Path, *, force: bool = False) -> UtilResult:
    """Add the utility (and the ones it requires) to its topic module in `directory`.

    Creates the module and __init__.py when missing. Raises UtilExistsError before
    writing anything if the module already defines the utility (unless force, which
    replaces just that definition).
    """
    path = directory / f"{spec.module}.py"
    chain = [*(UTILS[name] for name in spec.requires), spec]

    if path.exists():
        source = path.read_text()
        present = merge.defined_names(source)
        if spec.name in present and not force:
            raise UtilExistsError(path, spec.name)
        added = []
        for util in chain:
            if util is not spec and util.name in present:
                continue  # a required helper that's already there stays as it is
            replace = frozenset({util.name}) if util is spec else frozenset()
            source = merge.add_to_module(source, _snippet(util), replace)
            added.append(util.name)
        path.write_text(source)
        created_module = False
    else:
        directory.mkdir(parents=True, exist_ok=True)
        path.write_text(merge.new_module(MODULES[spec.module], [_snippet(u) for u in chain]))
        added = [util.name for util in chain]
        created_module = True

    init = directory / "__init__.py"
    created_init = not init.exists()
    if created_init:
        init.write_text(_env.get_template("__init__.py.jinja").render())
    exported = [line for name in added if (line := ensure_export(init, spec.module, name))]
    return UtilResult(path, created_module, added, created_init, exported)

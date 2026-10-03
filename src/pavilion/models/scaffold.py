"""Rendering SQLAlchemy models into a `models` package."""

from dataclasses import dataclass
from pathlib import Path

from jinja2 import Environment, PackageLoader, StrictUndefined

from pavilion.exports import ensure_export


@dataclass(frozen=True)
class ModelSpec:
    name: str  # class name, also what users type: `pavilion add model User`
    module: str  # file name without .py
    description: str

    @property
    def template(self) -> str:
        return f"{self.module}.py.jinja"


USER = ModelSpec(
    name="User",
    module="user",
    description="users: names, unique lowercase login, hashed password, active flag",
)

BASE_FIELDS = ModelSpec(
    name="BaseFields",
    module="base_fields",
    description="abstract parent: BigInteger id, created_at, updated_at",
)

MODELS: dict[str, ModelSpec] = {spec.name: spec for spec in [USER, BASE_FIELDS]}

# Shared by every model; created when missing, never overwritten.
SHARED_FILES = {"base.py": "base.py.jinja", "__init__.py": "__init__.py.jinja"}


class ModelExistsError(Exception):
    def __init__(self, path: Path):
        super().__init__(str(path))
        self.path = path


@dataclass(frozen=True)
class ModelResult:
    created: list[Path]
    # Shared files that already existed and were left as they are.
    kept: list[Path]
    # The re-export line appended to an existing __init__.py, if one was needed.
    exported: str | None


_env = Environment(
    loader=PackageLoader("pavilion.models", "templates"),
    undefined=StrictUndefined,
    trim_blocks=True,
    lstrip_blocks=True,
    keep_trailing_newline=True,
)


def scaffold_model(spec: ModelSpec, directory: Path, *, force: bool = False) -> ModelResult:
    """Write the model (and base.py/__init__.py if missing) into `directory`.

    Raises ModelExistsError before writing anything if the model file exists.
    """
    model_path = directory / f"{spec.module}.py"
    if model_path.exists() and not force:
        raise ModelExistsError(model_path)

    context = {"model": spec.name, "module": spec.module}
    directory.mkdir(parents=True, exist_ok=True)
    created, kept = [], []
    for name, template in SHARED_FILES.items():
        path = directory / name
        if path.exists():
            kept.append(path)
        else:
            path.write_text(_env.get_template(template).render(context))
            created.append(path)
    model_path.write_text(_env.get_template(spec.template).render(context))
    created.append(model_path)

    init = directory / "__init__.py"
    exported = ensure_export(init, spec.module, spec.name) if init in kept else None
    return ModelResult(created=created, kept=kept, exported=exported)

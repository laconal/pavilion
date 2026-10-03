"""Rendering application service classes into a `services` package."""

from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from jinja2 import Environment, PackageLoader, StrictUndefined

from pavilion.exports import ensure_export


class Client(StrEnum):
    ASYNC = "async"
    SYNC = "sync"


@dataclass(frozen=True)
class AppServiceSpec:
    name: str  # what users type: `pavilion add service redis`
    class_name: str
    module: str  # file name without .py; avoid package names like `redis` (would shadow)
    package: str  # PyPI dependency the generated code needs
    env_var: str  # setting it reads, added to .env
    env_default: str
    description: str
    # The `pavilion add docker` service that provides it locally, for a hint.
    docker_service: str | None = None

    @property
    def template(self) -> str:
        return f"{self.module}.py.jinja"


REDIS = AppServiceSpec(
    name="redis",
    class_name="RedisService",
    module="redis_service",
    package="redis",
    env_var="REDIS_URL",
    env_default="redis://localhost:6379",
    description="key-value store: create, get, update, delete",
    docker_service="redis",
)

SERVICES: dict[str, AppServiceSpec] = {spec.name: spec for spec in [REDIS]}


class ServiceFileExistsError(Exception):
    def __init__(self, path: Path):
        super().__init__(str(path))
        self.path = path


@dataclass(frozen=True)
class ServiceResult:
    created: list[Path]
    # The re-export line added to an existing __init__.py, if one was needed.
    exported: str | None


_env = Environment(
    loader=PackageLoader("pavilion.services", "templates"),
    undefined=StrictUndefined,
    trim_blocks=True,
    lstrip_blocks=True,
    keep_trailing_newline=True,
)


def service_path(spec: AppServiceSpec, directory: Path) -> Path:
    return directory / f"{spec.module}.py"


def scaffold_service(
    spec: AppServiceSpec, directory: Path, client: Client, *, force: bool = False
) -> ServiceResult:
    """Write the service (and __init__.py if missing) into `directory`.

    Raises ServiceFileExistsError before writing anything if the service file exists.
    """
    path = service_path(spec, directory)
    if path.exists() and not force:
        raise ServiceFileExistsError(path)

    is_async = client is Client.ASYNC
    context = {
        "module": spec.module,
        "class_name": spec.class_name,
        "default_url": spec.env_default,
        "is_async": is_async,
        "async_": "async " if is_async else "",
        "await_": "await " if is_async else "",
    }
    directory.mkdir(parents=True, exist_ok=True)
    created = []
    init = directory / "__init__.py"
    exported = None
    if init.exists():
        exported = ensure_export(init, spec.module, spec.class_name)
    else:
        init.write_text(_env.get_template("__init__.py.jinja").render(context))
        created.append(init)
    path.write_text(_env.get_template(spec.template).render(context))
    created.append(path)
    return ServiceResult(created=created, exported=exported)

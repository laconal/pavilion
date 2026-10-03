"""`pavilion add docker ...`"""

from enum import StrEnum
from pathlib import Path
from typing import Annotated, Callable

import typer
from rich.console import Console
from rich.table import Table

from pavilion import ui
from pavilion.compose import services
from pavilion.compose.file import (
    ServiceExistsError,
    add_service,
    add_services,
    find_compose_file,
    has_service,
)
from pavilion.compose.services import SERVICES, ServiceSpec
from pavilion.compose.services import celery as celery_spec

docker_app = typer.Typer(help="Add a service to docker-compose.yml.", no_args_is_help=True)

FileOption = Annotated[
    Path | None,
    typer.Option(
        "--file",
        "-f",
        help="Compose file to edit. Defaults to an existing compose file "
        "in the current directory, or docker-compose.yml.",
    ),
]
ForceOption = Annotated[
    bool, typer.Option("--force", help="Overwrite the service if it already exists.")
]


@docker_app.command("list")
def list_services() -> None:
    """Show available services."""
    table = Table(box=None, header_style="bold")
    table.add_column("Service")
    table.add_column("Versions")
    table.add_column("Image", no_wrap=True)  # keep image names whole; descriptions wrap
    table.add_column("Description")
    for spec in SERVICES.values():
        table.add_row(
            spec.name,
            ", ".join(spec.versions),
            spec.image_template.format(version="<version>"),
            spec.description,
        )
    table.add_row("celery", "-", "./Dockerfile", celery_spec.DESCRIPTION)
    Console().print(table)


def _choose_version(spec: ServiceSpec) -> str:
    return ui.select(
        f"Which {spec.name} version?",
        {version: f"{version}  ({spec.image(version)})" for version in spec.versions},
    )


def _already_exists(spec: ServiceSpec, path: Path) -> typer.Exit:
    return ui.fail(f"Service '{spec.name}' already exists in {path}. Use --force to overwrite.")


def _add(spec: ServiceSpec, version: str | None, file: Path | None, force: bool) -> None:
    path = file or find_compose_file(Path.cwd())
    created = not path.exists()

    # Check before prompting so we don't ask for a version we can't use.
    if not force and has_service(path, spec.name):
        raise _already_exists(spec, path)
    _require(spec.requires, spec.name, path)

    version = version or _choose_version(spec)
    try:
        add_service(path, spec, version, force=force)
    except ServiceExistsError:
        raise _already_exists(spec, path)

    action = "Created" if created else "Updated"
    typer.secho(
        f"{action} {path}: added service '{spec.name}' ({spec.image(version)}).",
        fg=typer.colors.GREEN,
    )


def _make_add_command(spec: ServiceSpec) -> Callable[..., None]:
    # An Enum is how Typer restricts an option to fixed choices (and lists them in --help).
    Version = StrEnum(f"{spec.name.title()}Version", {f"v{v}": v for v in spec.versions})
    VersionOption = Annotated[
        Version | None,
        typer.Option(
            "--version",
            help="Version to use. Prompts interactively if omitted.",
            show_default=False,
        ),
    ]

    def command(
        version: VersionOption = None, file: FileOption = None, force: ForceOption = False
    ) -> None:
        _add(spec, version.value if version else None, file, force)

    return command


# One subcommand per registered service: `pavilion add docker redis`, etc.
for _spec in SERVICES.values():
    docker_app.command(_spec.name, help=_spec.description)(_make_add_command(_spec))


def _require(names: tuple[str, ...], service: str, path: Path) -> None:
    if missing := [name for name in names if not has_service(path, name)]:
        raise ui.fail(
            f"{service} needs {', '.join(missing)} in {path}; add it first: "
            + " && ".join(f"pavilion add docker {name}" for name in missing)
        )


def _check_celery_app(app: str) -> str:
    if not celery_spec.APP_PATTERN.fullmatch(app):
        raise typer.BadParameter(
            f"{app!r} isn't a module path like app.worker or app.worker:celery_app"
        )
    return app


@docker_app.command("celery", help=celery_spec.DESCRIPTION)
def add_celery(
    app: Annotated[
        str | None,
        typer.Option(
            "--app",
            "-A",
            callback=lambda value: value and _check_celery_app(value),
            help=f"Celery app for `celery -A`, e.g. {celery_spec.DEFAULT_APP}. Prompts if omitted.",
            show_default=False,
        ),
    ] = None,
    file: FileOption = None,
    force: ForceOption = False,
) -> None:
    path = file or find_compose_file(Path.cwd())
    created = not path.exists()
    names = (celery_spec.WORKER, celery_spec.BEAT)

    # Check before prompting so we don't ask questions we can't act on.
    if not force and (taken := [name for name in names if has_service(path, name)]):
        raise ui.fail(f"{', '.join(taken)} already in {path}. Use --force to overwrite.")
    _require(celery_spec.REQUIRES, "celery", path)

    def validate(answer: str) -> bool | str:
        return bool(celery_spec.APP_PATTERN.fullmatch(answer)) or "Use a module path like app.worker"

    app = app or ui.text("Celery app (celery -A ...):", celery_spec.DEFAULT_APP, validate)
    add_services(path, celery_spec.celery_services(app), force=force)

    action = "Created" if created else "Updated"
    typer.secho(
        f"{action} {path}: added services {', '.join(repr(n) for n in names)} (celery -A {app}).",
        fg=typer.colors.GREEN,
    )
    if not (path.parent / "Dockerfile").exists():
        typer.secho(
            f"No Dockerfile next to {path.name}: both services build the project's image "
            "from ./Dockerfile, so add one before `docker compose up`.",
            fg=typer.colors.YELLOW,
        )

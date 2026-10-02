"""`pavilion add service ...`"""

from enum import StrEnum
from pathlib import Path
from typing import Annotated, Callable

import typer
from rich.console import Console
from rich.table import Table

from pavilion import ui
from pavilion.compose.file import ServiceExistsError, add_service, find_compose_file, has_service
from pavilion.compose.services import SERVICES, ServiceSpec

service_app = typer.Typer(help="Add a service to docker-compose.yml.", no_args_is_help=True)

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


@service_app.command("list")
def list_services() -> None:
    """Show available services."""
    table = Table("Service", "Versions", "Image", "Description", box=None, header_style="bold")
    for spec in SERVICES.values():
        table.add_row(
            spec.name,
            ", ".join(spec.versions),
            spec.image_template.format(version="<version>"),
            spec.description,
        )
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


# One subcommand per registered service: `pavilion add service redis`, etc.
for _spec in SERVICES.values():
    service_app.command(_spec.name, help=_spec.description)(_make_add_command(_spec))

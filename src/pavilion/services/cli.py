"""`pavilion add service list | <name>`"""

from pathlib import Path
from typing import Annotated, Callable

import typer
from rich.console import Console
from rich.table import Table

from pavilion import ui
from pavilion.compose.file import find_compose_file, has_service
from pavilion.deps import install as install_package
from pavilion.deps import project_root
from pavilion.env import EnvStatus, ensure_env_var, is_git_ignored
from pavilion.services.scaffold import (
    SERVICES,
    AppServiceSpec,
    Client,
    ServiceFileExistsError,
    scaffold_service,
    service_path,
)

service_app = typer.Typer(
    help="Generate application service classes (e.g. a Redis client).", no_args_is_help=True
)

ClientOption = Annotated[
    Client | None,
    typer.Option("--client", help="Async or sync client. Prompts if omitted.", show_default=False),
]
DirOption = Annotated[
    Path, typer.Option("--dir", "-d", help="Directory of the services package.")
]
InstallOption = Annotated[
    bool,
    typer.Option(
        "--install/--no-install",
        help="Add the client library to the project with `uv add` if it's missing.",
    ),
]
ForceOption = Annotated[
    bool, typer.Option("--force", help="Overwrite the service file if it exists.")
]


@service_app.command("list")
def list_services() -> None:
    """Show available services."""
    table = Table("Service", "Class", "Package", "Setting", "Description", box=None, header_style="bold")
    for spec in SERVICES.values():
        table.add_row(spec.name, spec.class_name, spec.package, spec.env_var, spec.description)
    Console().print(table)


def _shown(path: Path) -> Path:
    """`path` relative to the current directory when it's inside it, for messages."""
    return path.relative_to(Path.cwd()) if path.is_relative_to(Path.cwd()) else path


def _update_env(spec: AppServiceSpec, root: Path) -> None:
    env = _shown(root / ".env")
    setting = f"{spec.env_var}={spec.env_default}"
    match ensure_env_var(env, spec.env_var, spec.env_default):
        case EnvStatus.CREATED:
            typer.echo(f"Created {env} with {setting}")
        case EnvStatus.ADDED:
            typer.echo(f"Added {setting} to {env}")
        case EnvStatus.EXISTS:
            typer.echo(f"{spec.env_var} is already set in {env}; left unchanged.")
    if is_git_ignored(env) is False:
        typer.secho(
            f"{env} isn't git-ignored; add `.env` to .gitignore before it holds credentials.",
            fg=typer.colors.YELLOW,
        )


def _add(
    spec: AppServiceSpec, client: Client | None, directory: Path, install: bool, force: bool
) -> None:
    # Check before prompting so we don't ask questions we can't act on.
    if not force and (path := service_path(spec, directory)).exists():
        raise ui.fail(f"{path} already exists. Use --force to overwrite.")
    client = client or ui.select(
        f"{spec.class_name} client:",
        {
            Client.ASYNC: "Async  (asyncio: FastAPI and other async apps)",
            Client.SYNC: "Sync",
        },
    )

    result = scaffold_service(spec, directory, client, force=force)
    typer.secho(f"Generated {spec.class_name} ({client}) in {directory}/:", fg=typer.colors.GREEN)
    for path in result.created:
        typer.echo(f"  {path}")
    if result.exported:
        typer.echo(f"  {directory / '__init__.py'} (added `{result.exported}`)")

    root = project_root(Path.cwd())
    _update_env(spec, root)
    if install:
        install_package(spec.package)
    if spec.docker_service and not has_service(find_compose_file(root), spec.docker_service):
        typer.echo(
            f"Tip: no {spec.docker_service} in the compose file; "
            f"`pavilion add docker {spec.docker_service}` adds one for local development."
        )


def _make_add_command(spec: AppServiceSpec) -> Callable[..., None]:
    def command(
        client: ClientOption = None,
        directory: DirOption = Path("services"),
        install: InstallOption = True,
        force: ForceOption = False,
    ) -> None:
        _add(spec, client, directory, install, force)

    return command


# One subcommand per registered service: `pavilion add service redis`, etc.
for _spec in SERVICES.values():
    service_app.command(_spec.name, help=_spec.description)(_make_add_command(_spec))

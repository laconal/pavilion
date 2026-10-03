"""`pavilion add model list | <Name>`"""

from pathlib import Path
from typing import Annotated, Callable

import typer
from rich.console import Console
from rich.table import Table

from pavilion import ui
from pavilion.deps import install as install_package
from pavilion.models.scaffold import MODELS, ModelExistsError, ModelSpec, scaffold_model

PACKAGE = "sqlalchemy"
DEFAULT_DIR = Path("models")

# Model names are case-insensitive: `add model user` runs the `User` command.
_CANONICAL = {name.lower(): name for name in MODELS}

model_app = typer.Typer(
    help="Generate a SQLAlchemy model, and add SQLAlchemy to the project if needed.",
    context_settings={"token_normalize_func": lambda token: _CANONICAL.get(token.lower(), token)},
)

DirOption = Annotated[
    Path, typer.Option("--dir", "-d", help="Directory of the models package.")
]
InstallOption = Annotated[
    bool,
    typer.Option(
        "--install/--no-install",
        help=f"Add {PACKAGE} to the project with `uv add` if it isn't a dependency yet.",
    ),
]
ForceOption = Annotated[
    bool, typer.Option("--force", help="Overwrite the model file if it exists.")
]


def _add(spec: ModelSpec, directory: Path, install: bool, force: bool) -> None:
    try:
        result = scaffold_model(spec, directory, force=force)
    except ModelExistsError as e:
        raise ui.fail(f"{e.path} already exists. Use --force to overwrite.")

    typer.secho(f"Generated {spec.name} model in {directory}/:", fg=typer.colors.GREEN)
    for path in result.created:
        typer.echo(f"  {path}")
    for path in result.kept:
        if path.name == "__init__.py" and result.exported:
            typer.echo(f"  {path} (added `{result.exported}`)")
        else:
            typer.echo(f"  {path} (kept existing)")

    if install:
        install_package(PACKAGE)


@model_app.callback(invoke_without_command=True)
def choose_model(ctx: typer.Context) -> None:
    """Without a model name: pick one from a menu (in a terminal) or show this help."""
    if ctx.invoked_subcommand is not None:
        return
    if not ui.interactive():
        typer.echo(ctx.get_help())
        raise typer.Exit()
    spec = ui.select(
        "Which model?", {s: f"{s.name:<10} ({s.description})" for s in MODELS.values()}
    )
    _add(spec, DEFAULT_DIR, install=True, force=False)


@model_app.command("list")
def list_models() -> None:
    """Show available models."""
    table = Table("Model", "File", "Description", box=None, header_style="bold")
    for spec in MODELS.values():
        table.add_row(spec.name, f"{spec.module}.py", spec.description)
    Console().print(table)


def _make_add_command(spec: ModelSpec) -> Callable[..., None]:
    def command(
        directory: DirOption = DEFAULT_DIR,
        install: InstallOption = True,
        force: ForceOption = False,
    ) -> None:
        _add(spec, directory, install, force)

    return command


# One subcommand per registered model: `pavilion add model User`, etc.
for _spec in MODELS.values():
    model_app.command(_spec.name, help=_spec.description)(_make_add_command(_spec))

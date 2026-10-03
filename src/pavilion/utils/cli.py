"""`pavilion add util list | <name>`"""

from pathlib import Path
from typing import Annotated, Callable

import typer
from rich.console import Console
from rich.table import Table

from pavilion import ui
from pavilion.utils.scaffold import UTILS, UtilExistsError, UtilSpec, scaffold_util

util_app = typer.Typer(help="Generate small standalone helper functions.", no_args_is_help=True)

DirOption = Annotated[Path, typer.Option("--dir", "-d", help="Directory of the utils package.")]
ForceOption = Annotated[
    bool, typer.Option("--force", help="Overwrite the utility's file if it exists.")
]


@util_app.command("list")
def list_utils() -> None:
    """Show available utilities."""
    table = Table("Util", "File", "Description", box=None, header_style="bold")
    for spec in UTILS.values():
        table.add_row(spec.name, f"{spec.module}.py", spec.description)
    Console().print(table)


def _add(spec: UtilSpec, directory: Path, force: bool) -> None:
    try:
        result = scaffold_util(spec, directory, force=force)
    except UtilExistsError as e:
        raise ui.fail(f"{e.name} is already in {e.path}. Use --force to replace it.")

    functions = ", ".join(f"{name}()" for name in result.added)
    if result.created_module:
        typer.secho(f"Generated {result.path} with {functions}", fg=typer.colors.GREEN)
    else:
        typer.secho(f"Added {functions} to {result.path}", fg=typer.colors.GREEN)
    init = directory / "__init__.py"
    if result.created_init:
        typer.echo(f"  {init} (created)")
    for line in result.exported:
        typer.echo(f"  {init} (added `{line}`)")


def _make_add_command(spec: UtilSpec) -> Callable[..., None]:
    def command(directory: DirOption = Path("utils"), force: ForceOption = False) -> None:
        _add(spec, directory, force)

    return command


# One subcommand per registered utility: `pavilion add util generate_password`, etc.
for _spec in UTILS.values():
    util_app.command(_spec.name, help=_spec.description)(_make_add_command(_spec))

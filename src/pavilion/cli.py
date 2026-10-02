"""Root command: wires each feature's commands into `pavilion add ...`."""

import typer

from pavilion.auth.cli import add_auth
from pavilion.compose.cli import service_app
from pavilion.keys.cli import add_keys

app = typer.Typer(help="Pavilion: project scaffolder.", no_args_is_help=True)
add_app = typer.Typer(help="Add components to the current project.", no_args_is_help=True)
app.add_typer(add_app, name="add")

add_app.add_typer(service_app, name="service")
add_app.command("keys")(add_keys)
add_app.command("auth")(add_auth)

"""Root command: wires each feature's commands into `pavilion add ...`."""

import typer

from pavilion.auth.cli import add_auth
from pavilion.compose.cli import docker_app
from pavilion.keys.cli import add_keys
from pavilion.models.cli import model_app
from pavilion.services.cli import service_app
from pavilion.utils.cli import util_app

app = typer.Typer(help="Pavilion: project scaffolder.", no_args_is_help=True)
add_app = typer.Typer(help="Add components to the current project.", no_args_is_help=True)
app.add_typer(add_app, name="add")

add_app.add_typer(docker_app, name="docker")
add_app.command("keys")(add_keys)
add_app.command("auth")(add_auth)
add_app.add_typer(model_app, name="model")
add_app.add_typer(service_app, name="service")
add_app.add_typer(util_app, name="util")

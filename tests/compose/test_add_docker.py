import shutil
import subprocess

import pytest
from ruamel.yaml import YAML
from typer.testing import CliRunner

from pavilion.cli import app

runner = CliRunner()


def load(path):
    return YAML(typ="safe").load(path)


def test_creates_compose_file(tmp_path):
    result = runner.invoke(app, ["add", "docker", "redis"])

    assert result.exit_code == 0, result.output
    data = load(tmp_path / "docker-compose.yml")
    assert data["services"]["redis"]["image"].startswith("redis:")
    assert "redis_data" in data["volumes"]


def test_appends_to_existing_file_and_keeps_comments(tmp_path):
    compose = tmp_path / "compose.yaml"
    compose.write_text(
        "# my app\n"
        "services:\n"
        "  web:\n"
        "    image: nginx  # frontend\n"
    )

    result = runner.invoke(app, ["add", "docker", "redis"])

    assert result.exit_code == 0, result.output
    assert not (tmp_path / "docker-compose.yml").exists()
    text = compose.read_text()
    assert "# my app" in text
    assert "# frontend" in text
    assert set(load(compose)["services"]) == {"web", "redis"}


def test_refuses_to_overwrite_without_force(tmp_path):
    runner.invoke(app, ["add", "docker", "redis"])
    compose = tmp_path / "docker-compose.yml"
    compose.write_text(compose.read_text().replace("redis:8-alpine", "redis:custom"))

    result = runner.invoke(app, ["add", "docker", "redis"])
    assert result.exit_code == 1
    assert load(compose)["services"]["redis"]["image"] == "redis:custom"

    result = runner.invoke(app, ["add", "docker", "redis", "--force"])
    assert result.exit_code == 0
    assert load(compose)["services"]["redis"]["image"] == "redis:8-alpine"


def test_adds_postgres_next_to_redis(tmp_path):
    runner.invoke(app, ["add", "docker", "redis"])
    result = runner.invoke(app, ["add", "docker", "postgres"])

    assert result.exit_code == 0, result.output
    data = load(tmp_path / "docker-compose.yml")
    assert set(data["services"]) == {"redis", "postgres"}
    assert set(data["volumes"]) == {"redis_data", "postgres_data"}
    env = data["services"]["postgres"]["environment"]
    assert set(env) == {"POSTGRES_USER", "POSTGRES_PASSWORD", "POSTGRES_DB"}


def test_list_services():
    result = runner.invoke(app, ["add", "docker", "list"])

    assert result.exit_code == 0, result.output
    assert "redis" in result.output
    assert "postgres" in result.output
    assert "pgbouncer" in result.output


def test_unknown_service():
    result = runner.invoke(app, ["add", "docker", "nope"])

    assert result.exit_code != 0
    assert "No such command" in result.output


def test_version_option_picks_image_and_data_dir(tmp_path):
    result = runner.invoke(app, ["add", "docker", "postgres", "--version", "17"])

    assert result.exit_code == 0, result.output
    postgres = load(tmp_path / "docker-compose.yml")["services"]["postgres"]
    assert postgres["image"] == "postgres:17-alpine"
    assert postgres["volumes"] == ["postgres_data:/var/lib/postgresql/data"]


def test_defaults_to_newest_version_without_a_terminal(tmp_path):
    result = runner.invoke(app, ["add", "docker", "postgres"])

    assert result.exit_code == 0, result.output
    postgres = load(tmp_path / "docker-compose.yml")["services"]["postgres"]
    assert postgres["image"] == "postgres:18-alpine"
    assert postgres["volumes"] == ["postgres_data:/var/lib/postgresql"]


def test_rejects_unknown_version():
    result = runner.invoke(app, ["add", "docker", "postgres", "--version", "9"])

    assert result.exit_code == 2
    assert "Invalid value" in result.output


def test_pgbouncer_requires_postgres(tmp_path):
    runner.invoke(app, ["add", "docker", "redis"])
    before = (tmp_path / "docker-compose.yml").read_text()

    result = runner.invoke(app, ["add", "docker", "pgbouncer"])

    assert result.exit_code == 1
    assert "pgbouncer needs postgres" in result.output
    assert "pavilion add docker postgres" in result.output
    assert (tmp_path / "docker-compose.yml").read_text() == before


def test_pgbouncer_in_front_of_postgres(tmp_path):
    runner.invoke(app, ["add", "docker", "postgres"])

    result = runner.invoke(app, ["add", "docker", "pgbouncer"])

    assert result.exit_code == 0, result.output
    pgbouncer = load(tmp_path / "docker-compose.yml")["services"]["pgbouncer"]
    assert pgbouncer["image"] == "edoburu/pgbouncer:v1.26.0-p0"
    assert pgbouncer["depends_on"] == {"postgres": {"condition": "service_healthy"}}
    assert pgbouncer["ports"] == ["6432:5432"]
    env = pgbouncer["environment"]
    assert env["DATABASE_URL"].endswith("@postgres:5432")  # no db name: pool every database
    assert env["AUTH_TYPE"] == "scram-sha-256"
    assert env["POOL_MODE"] == "transaction"


def test_pgbouncer_version_maps_to_image_tag(tmp_path):
    runner.invoke(app, ["add", "docker", "postgres"])

    runner.invoke(app, ["add", "docker", "pgbouncer", "--version", "1.24.1"])

    image = load(tmp_path / "docker-compose.yml")["services"]["pgbouncer"]["image"]
    assert image == "edoburu/pgbouncer:v1.24.1-p1"


def test_long_values_stay_on_one_line(tmp_path):
    runner.invoke(app, ["add", "docker", "postgres"])
    runner.invoke(app, ["add", "docker", "pgbouncer"])

    lines = (tmp_path / "docker-compose.yml").read_text().splitlines()
    assert any(line.strip().startswith("DATABASE_URL: postgres://") for line in lines)


@pytest.mark.skipif(shutil.which("docker") is None, reason="needs Docker")
def test_generated_file_passes_docker_compose_config(tmp_path):
    for service in ["redis", "postgres", "pgbouncer"]:
        runner.invoke(app, ["add", "docker", service])

    result = subprocess.run(
        ["docker", "compose", "-f", "docker-compose.yml", "config", "-q"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr

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
    assert any(line.split()[:3] == ["celery", "-", "./Dockerfile"] for line in result.output.splitlines())


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
    for service in ["redis", "postgres", "pgbouncer", "celery"]:
        runner.invoke(app, ["add", "docker", service])

    result = subprocess.run(
        ["docker", "compose", "-f", "docker-compose.yml", "config", "-q"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr


def test_celery_requires_redis(tmp_path):
    result = runner.invoke(app, ["add", "docker", "celery"])

    assert result.exit_code == 1
    assert "celery needs redis" in result.output
    assert "pavilion add docker redis" in result.output
    assert not (tmp_path / "docker-compose.yml").exists()


def test_celery_worker_and_beat(tmp_path):
    runner.invoke(app, ["add", "docker", "redis"])

    result = runner.invoke(app, ["add", "docker", "celery", "-A", "project.tasks:celery_app"])

    assert result.exit_code == 0, result.output
    assert "added services 'celery-worker', 'celery-beat'" in result.output
    services = load(tmp_path / "docker-compose.yml")["services"]
    worker, beat = services["celery-worker"], services["celery-beat"]
    for service in (worker, beat):
        assert service["build"] == "."
        assert service["depends_on"] == {"redis": {"condition": "service_healthy"}}
        assert service["env_file"] == [{"path": ".env", "required": False}]
        assert service["environment"] == {
            "CELERY_BROKER_URL": "redis://redis:6379/0",
            "CELERY_RESULT_BACKEND": "redis://redis:6379/1",
            "REDIS_URL": "redis://redis:6379",
        }
    assert worker["command"] == "celery -A project.tasks:celery_app worker --loglevel=info"
    assert worker["healthcheck"]["test"] == [
        "CMD-SHELL", "celery -A project.tasks:celery_app inspect ping -d celery@$$HOSTNAME"
    ]
    assert beat["command"] == (
        "celery -A project.tasks:celery_app beat --loglevel=info"
        " --schedule /tmp/celerybeat-schedule"
    )
    assert "    build: .\n" in (tmp_path / "docker-compose.yml").read_text()  # not quoted


def test_celery_app_defaults_without_a_terminal(tmp_path):
    runner.invoke(app, ["add", "docker", "redis"])

    runner.invoke(app, ["add", "docker", "celery"])

    worker = load(tmp_path / "docker-compose.yml")["services"]["celery-worker"]
    assert worker["command"] == "celery -A app.worker worker --loglevel=info"


@pytest.mark.parametrize("bad", ["bad app", "app/worker", "app.", "1app"])
def test_celery_rejects_invalid_app(bad):
    result = runner.invoke(app, ["add", "docker", "celery", "-A", bad])

    assert result.exit_code == 2
    assert "isn't a module path" in result.output


def test_celery_refuses_to_overwrite_without_force(tmp_path):
    runner.invoke(app, ["add", "docker", "redis"])
    runner.invoke(app, ["add", "docker", "celery", "-A", "first"])

    result = runner.invoke(app, ["add", "docker", "celery", "-A", "second"])
    assert result.exit_code == 1
    assert "celery-worker, celery-beat already in" in result.output

    result = runner.invoke(app, ["add", "docker", "celery", "-A", "second", "--force"])
    assert result.exit_code == 0, result.output
    services = load(tmp_path / "docker-compose.yml")["services"]
    assert services["celery-beat"]["command"].startswith("celery -A second beat")


def test_celery_warns_without_dockerfile(tmp_path):
    runner.invoke(app, ["add", "docker", "redis"])
    result = runner.invoke(app, ["add", "docker", "celery"])
    assert "No Dockerfile next to docker-compose.yml" in result.output

    (tmp_path / "Dockerfile").write_text("FROM python:3.12-slim\n")
    result = runner.invoke(app, ["add", "docker", "celery", "--force"])
    assert "Dockerfile" not in result.output

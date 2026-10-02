from ruamel.yaml import YAML
from typer.testing import CliRunner

from pavilion.cli import app

runner = CliRunner()


def load(path):
    return YAML(typ="safe").load(path)


def test_creates_compose_file(tmp_path):
    result = runner.invoke(app, ["add", "service", "redis"])

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

    result = runner.invoke(app, ["add", "service", "redis"])

    assert result.exit_code == 0, result.output
    assert not (tmp_path / "docker-compose.yml").exists()
    text = compose.read_text()
    assert "# my app" in text
    assert "# frontend" in text
    assert set(load(compose)["services"]) == {"web", "redis"}


def test_refuses_to_overwrite_without_force(tmp_path):
    runner.invoke(app, ["add", "service", "redis"])
    compose = tmp_path / "docker-compose.yml"
    compose.write_text(compose.read_text().replace("redis:8-alpine", "redis:custom"))

    result = runner.invoke(app, ["add", "service", "redis"])
    assert result.exit_code == 1
    assert load(compose)["services"]["redis"]["image"] == "redis:custom"

    result = runner.invoke(app, ["add", "service", "redis", "--force"])
    assert result.exit_code == 0
    assert load(compose)["services"]["redis"]["image"] == "redis:8-alpine"


def test_adds_postgres_next_to_redis(tmp_path):
    runner.invoke(app, ["add", "service", "redis"])
    result = runner.invoke(app, ["add", "service", "postgres"])

    assert result.exit_code == 0, result.output
    data = load(tmp_path / "docker-compose.yml")
    assert set(data["services"]) == {"redis", "postgres"}
    assert set(data["volumes"]) == {"redis_data", "postgres_data"}
    env = data["services"]["postgres"]["environment"]
    assert set(env) == {"POSTGRES_USER", "POSTGRES_PASSWORD", "POSTGRES_DB"}


def test_list_services():
    result = runner.invoke(app, ["add", "service", "list"])

    assert result.exit_code == 0, result.output
    assert "redis" in result.output
    assert "postgres" in result.output


def test_unknown_service():
    result = runner.invoke(app, ["add", "service", "nope"])

    assert result.exit_code != 0
    assert "No such command" in result.output


def test_version_option_picks_image_and_data_dir(tmp_path):
    result = runner.invoke(app, ["add", "service", "postgres", "--version", "17"])

    assert result.exit_code == 0, result.output
    postgres = load(tmp_path / "docker-compose.yml")["services"]["postgres"]
    assert postgres["image"] == "postgres:17-alpine"
    assert postgres["volumes"] == ["postgres_data:/var/lib/postgresql/data"]


def test_defaults_to_newest_version_without_a_terminal(tmp_path):
    result = runner.invoke(app, ["add", "service", "postgres"])

    assert result.exit_code == 0, result.output
    postgres = load(tmp_path / "docker-compose.yml")["services"]["postgres"]
    assert postgres["image"] == "postgres:18-alpine"
    assert postgres["volumes"] == ["postgres_data:/var/lib/postgresql"]


def test_rejects_unknown_version():
    result = runner.invoke(app, ["add", "service", "postgres", "--version", "9"])

    assert result.exit_code == 2
    assert "Invalid value" in result.output

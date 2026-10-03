import os
import subprocess
import sys
import textwrap

import pytest
from typer.testing import CliRunner

from pavilion.cli import app

runner = CliRunner()


def run_generated(tmp_path, script, redis_url):
    """Run `script` against the generated package with REDIS_URL set, like a .env would."""
    result = subprocess.run(
        [sys.executable, "-c", textwrap.dedent(script)],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        env={**os.environ, "REDIS_URL": redis_url},
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "ok"


# One script for both clients: `{a}` becomes "await " for the async one.
FLOW = """
import asyncio
from datetime import timedelta

from services import RedisService


async def main():
    {with_} RedisService() as redis:  # URL from REDIS_URL
        assert {a}redis.get("k") is None
        assert {a}redis.create("k", "v1") is True
        assert {a}redis.create("k", "other") is False  # already exists
        assert {a}redis.get("k") == "v1"

        assert {a}redis.update("k", "v2") is True
        assert {a}redis.get("k") == "v2"
        assert {a}redis.update("missing", "v") is False
        assert {a}redis.get("missing") is None  # update never creates

        assert {a}redis.create("t", "v", ttl=100) is True
        assert 0 < {a}redis.client.ttl("t") <= 100
        assert {a}redis.update("t", "v2") is True
        assert 0 < {a}redis.client.ttl("t") <= 100  # no ttl given: expiry kept
        assert {a}redis.update("t", "v3", ttl=timedelta(seconds=500)) is True
        assert 100 < {a}redis.client.ttl("t") <= 500

        assert {a}redis.delete("k") is True
        assert {a}redis.delete("k") is False
        assert {a}redis.get("k") is None
    print("ok")


asyncio.run(main())
"""


@pytest.mark.parametrize("client", ["async", "sync"])
def test_generated_service_works(tmp_path, redis_url, client):
    result = runner.invoke(app, ["add", "service", "redis", "--client", client, "--no-install"])

    assert result.exit_code == 0, result.output
    assert f"Generated RedisService ({client})" in result.output
    a, with_ = ("await ", "async with") if client == "async" else ("", "with")
    run_generated(tmp_path, FLOW.format(a=a, with_=with_), redis_url)


def test_explicit_url_wins_over_environment(tmp_path, redis_url):
    runner.invoke(app, ["add", "service", "redis", "--client", "sync", "--no-install"])
    script = f"""
    from services import RedisService

    with RedisService("{redis_url}") as redis:
        redis.create("x", "1")
    with RedisService("redis://127.0.0.1:1") as unreachable:
        try:
            unreachable.get("x")
        except Exception:
            print("ok")
    """
    run_generated(tmp_path, script, "redis://127.0.0.1:1")


def test_list_services():
    result = runner.invoke(app, ["add", "service", "list"])

    assert result.exit_code == 0, result.output
    assert result.output.splitlines()[1].split()[:4] == [
        "redis", "RedisService", "redis", "REDIS_URL"
    ]


def test_creates_env_file(tmp_path):
    result = runner.invoke(app, ["add", "service", "redis", "--no-install"])

    assert result.exit_code == 0, result.output
    assert (tmp_path / ".env").read_text() == "REDIS_URL=redis://localhost:6379\n"
    assert "Created .env with REDIS_URL=redis://localhost:6379" in result.output


@pytest.mark.parametrize("existing", ["DEBUG=1", "DEBUG=1\n", ""])
def test_appends_to_existing_env_file(tmp_path, existing):
    (tmp_path / ".env").write_text(existing)

    result = runner.invoke(app, ["add", "service", "redis", "--no-install"])

    assert result.exit_code == 0, result.output
    expected = ("DEBUG=1\n" if existing else "") + "REDIS_URL=redis://localhost:6379\n"
    assert (tmp_path / ".env").read_text() == expected
    assert "Added REDIS_URL=redis://localhost:6379 to .env" in result.output


@pytest.mark.parametrize(
    "existing", ["REDIS_URL=redis://cache:6379/2\n", "export REDIS_URL = redis://x\n"]
)
def test_keeps_existing_redis_url(tmp_path, existing):
    (tmp_path / ".env").write_text("DEBUG=1\n" + existing)

    result = runner.invoke(app, ["add", "service", "redis", "--no-install"])

    assert result.exit_code == 0, result.output
    assert (tmp_path / ".env").read_text() == "DEBUG=1\n" + existing
    assert "already set in .env; left unchanged" in result.output


def test_env_goes_to_project_root(tmp_path, monkeypatch):
    (tmp_path / "pyproject.toml").write_text('[project]\nname = "app"\ndependencies = []\n')
    (tmp_path / "src").mkdir()
    monkeypatch.chdir(tmp_path / "src")

    runner.invoke(app, ["add", "service", "redis", "--no-install"])

    assert (tmp_path / ".env").exists()
    assert not (tmp_path / "src" / ".env").exists()
    assert (tmp_path / "src" / "services" / "redis_service.py").exists()


def _git_init(path):
    subprocess.run(["git", "init", "-q", str(path)], check=True)


def test_warns_when_env_is_not_git_ignored(tmp_path):
    _git_init(tmp_path)

    result = runner.invoke(app, ["add", "service", "redis", "--no-install"])

    assert ".env isn't git-ignored" in result.output


def test_no_warning_when_env_is_git_ignored(tmp_path):
    _git_init(tmp_path)
    (tmp_path / ".gitignore").write_text(".env\n")

    result = runner.invoke(app, ["add", "service", "redis", "--no-install"])

    assert "git-ignored" not in result.output


def test_installs_redis_package(tmp_path, uv_calls):
    (tmp_path / "pyproject.toml").write_text('[project]\nname = "app"\ndependencies = []\n')

    result = runner.invoke(app, ["add", "service", "redis"])

    assert result.exit_code == 0, result.output
    assert uv_calls == [(["/usr/bin/uv", "add", "redis"], tmp_path)]


def test_no_install(tmp_path, uv_calls):
    (tmp_path / "pyproject.toml").write_text('[project]\nname = "app"\ndependencies = []\n')

    runner.invoke(app, ["add", "service", "redis", "--no-install"])

    assert uv_calls == []


def test_refuses_to_overwrite_without_force(tmp_path):
    runner.invoke(app, ["add", "service", "redis", "--no-install"])
    service = tmp_path / "services" / "redis_service.py"
    service.write_text("# edited\n")

    result = runner.invoke(app, ["add", "service", "redis", "--no-install"])
    assert result.exit_code == 1
    assert service.read_text() == "# edited\n"

    result = runner.invoke(app, ["add", "service", "redis", "--client", "sync", "--no-install", "--force"])
    assert result.exit_code == 0, result.output
    assert "from redis import Redis" in service.read_text()


def test_existing_init_gets_an_export_line(tmp_path):
    (tmp_path / "services").mkdir()
    (tmp_path / "services" / "__init__.py").write_text("from .email import EmailService as EmailService\n")

    result = runner.invoke(app, ["add", "service", "redis", "--no-install"])

    assert result.exit_code == 0, result.output
    assert (tmp_path / "services" / "__init__.py").read_text() == (
        "from .email import EmailService as EmailService\n"
        "from .redis_service import RedisService as RedisService\n"
    )


def test_suggests_docker_redis_only_when_missing(tmp_path):
    result = runner.invoke(app, ["add", "service", "redis", "--no-install"])
    assert "`pavilion add docker redis`" in result.output

    runner.invoke(app, ["add", "docker", "redis", "--version", "8"])
    result = runner.invoke(app, ["add", "service", "redis", "--no-install", "--force"])
    assert "pavilion add docker redis" not in result.output


def test_rejects_unknown_client():
    result = runner.invoke(app, ["add", "service", "redis", "--client", "threads"])

    assert result.exit_code == 2
    assert "Invalid value" in result.output

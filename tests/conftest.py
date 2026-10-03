import shutil
import subprocess
import uuid

import pytest

from pavilion import deps


@pytest.fixture(autouse=True)
def in_tmp(tmp_path, monkeypatch):
    """Run every test from an empty directory, as a user would run pavilion in a project."""
    monkeypatch.chdir(tmp_path)


class FakeUv(list):
    """Records `uv add` calls instead of running them; set `returncode` to simulate failure."""

    returncode = 0

    def run(self, command, cwd):
        self.append((command, cwd))
        return self.returncode


@pytest.fixture
def uv_calls(monkeypatch):
    """Never run a real `uv add` in tests: this replaces the two places deps touches uv."""
    fake = FakeUv()
    monkeypatch.setattr(deps, "_find_uv", lambda: "/usr/bin/uv")
    monkeypatch.setattr(deps, "_run", fake.run)
    return fake


@pytest.fixture(scope="session")
def start_container():
    """Factory: start(image, port, env) -> host port of a throwaway Docker container.

    Containers are named pavilion-test-*, bound to a random 127.0.0.1 port, and removed
    at the end of the test session. Skips the test if Docker isn't available.
    """
    docker = shutil.which("docker")
    started = []

    def start(image: str, port: int, env: dict[str, str] | None = None) -> int:
        if docker is None:
            pytest.skip(f"needs Docker for {image}")
        name = f"pavilion-test-{uuid.uuid4().hex[:8]}"
        env_args = [arg for key, value in (env or {}).items() for arg in ("-e", f"{key}={value}")]
        result = subprocess.run(
            [docker, "run", "-d", "--rm", "--name", name, *env_args,
             "-p", f"127.0.0.1::{port}", image],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            pytest.skip(f"couldn't start {image}: {result.stderr.strip()}")
        started.append(name)
        mapping = subprocess.run(
            [docker, "port", name, f"{port}/tcp"], capture_output=True, text=True, check=True
        )
        return int(mapping.stdout.splitlines()[0].rsplit(":", 1)[1])

    yield start
    for name in started:
        subprocess.run([docker, "rm", "-f", name], capture_output=True)

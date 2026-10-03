"""A real Postgres for the generated models: Postgres is pavilion's target database.

Set PAVILION_TEST_POSTGRES_URL to an admin URL (e.g. in CI) to use an existing server:
    postgresql://postgres:secret@localhost:5432/postgres
Otherwise a throwaway postgres:18 container is started once per test session (and
removed afterwards). Each test gets its own fresh database. Without either, the
database tests are skipped.
"""

import os
import shutil
import subprocess
import time
import uuid

import psycopg
import pytest
from sqlalchemy.engine import make_url

IMAGE = "postgres:18"
PASSWORD = "pavilion"


def _wait_until_ready(url: str, timeout: float = 60) -> None:
    deadline = time.monotonic() + timeout
    while True:
        try:
            with psycopg.connect(url, connect_timeout=2):
                return
        except psycopg.OperationalError:
            if time.monotonic() > deadline:
                raise
            time.sleep(0.3)


@pytest.fixture(scope="session")
def postgres_admin_url():
    if url := os.environ.get("PAVILION_TEST_POSTGRES_URL"):
        yield url
        return
    docker = shutil.which("docker")
    if docker is None:
        pytest.skip("needs Docker or PAVILION_TEST_POSTGRES_URL")

    name = f"pavilion-test-{uuid.uuid4().hex[:8]}"
    started = subprocess.run(
        [docker, "run", "-d", "--rm", "--name", name, "-e", f"POSTGRES_PASSWORD={PASSWORD}",
         "-p", "127.0.0.1::5432", IMAGE],
        capture_output=True,
        text=True,
    )
    if started.returncode != 0:
        pytest.skip(f"couldn't start {IMAGE}: {started.stderr.strip()}")
    try:
        port = subprocess.run(
            [docker, "port", name, "5432/tcp"], capture_output=True, text=True, check=True
        ).stdout.splitlines()[0].rsplit(":", 1)[1]
        url = f"postgresql://postgres:{PASSWORD}@127.0.0.1:{port}/postgres"
        _wait_until_ready(url)
        yield url
    finally:
        subprocess.run([docker, "rm", "-f", name], capture_output=True)


@pytest.fixture
def database_url(postgres_admin_url):
    """SQLAlchemy URL (psycopg driver) of an empty database, dropped after the test."""
    name = f"test_{uuid.uuid4().hex[:12]}"
    with psycopg.connect(postgres_admin_url, autocommit=True) as connection:
        connection.execute(f'CREATE DATABASE "{name}"')
    url = make_url(postgres_admin_url).set(drivername="postgresql+psycopg", database=name)
    yield url.render_as_string(hide_password=False)
    with psycopg.connect(postgres_admin_url, autocommit=True) as connection:
        connection.execute(f'DROP DATABASE "{name}" WITH (FORCE)')

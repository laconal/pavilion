"""A real Redis for the generated services.

Set PAVILION_TEST_REDIS_URL (e.g. in CI) to use an existing server; otherwise a
throwaway redis:7-alpine container is started once per test session
(`start_container` in tests/conftest.py). The database is flushed before each test,
so don't point it at a Redis holding data you care about.
"""

import os
import time

import pytest
import redis

IMAGE = "redis:7-alpine"  # KEEPTTL (used by update) needs Redis >= 6


def _wait_until_ready(url: str, timeout: float = 30) -> None:
    deadline = time.monotonic() + timeout
    while True:
        try:
            with redis.Redis.from_url(url, socket_connect_timeout=2) as client:
                client.ping()
                return
        except redis.ConnectionError:
            if time.monotonic() > deadline:
                raise
            time.sleep(0.2)


@pytest.fixture(scope="session")
def redis_server_url(start_container):
    if url := os.environ.get("PAVILION_TEST_REDIS_URL"):
        return url
    url = f"redis://127.0.0.1:{start_container(IMAGE, 6379)}"
    _wait_until_ready(url)
    return url


@pytest.fixture
def redis_url(redis_server_url):
    """URL of an empty Redis database."""
    with redis.Redis.from_url(redis_server_url) as client:
        client.flushdb()
    return redis_server_url

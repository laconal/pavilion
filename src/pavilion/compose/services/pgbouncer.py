from typing import Any

from pavilion.compose.services.base import ServiceSpec

# PgBouncer has no official image; edoburu/pgbouncer is the de facto one and is
# configured entirely through environment variables (see its /entrypoint.sh).


def _build(version: str) -> dict[str, Any]:
    return {
        "restart": "unless-stopped",
        "environment": {
            # The postgres service's credentials; "postgres" is its host on the compose
            # network. No database name in the URL: every database is pooled.
            "DATABASE_URL": (
                "postgres://${POSTGRES_USER:-postgres}:${POSTGRES_PASSWORD:-postgres}"
                "@postgres:5432"
            ),
            # Postgres 14+ stores scram-sha-256 passwords; the image defaults to md5.
            "AUTH_TYPE": "scram-sha-256",
            # A server connection per transaction, not per client: the usual web-app mode.
            "POOL_MODE": "transaction",
            "DEFAULT_POOL_SIZE": "20",
            "MAX_CLIENT_CONN": "200",
            # PgBouncer 1.21+ can track prepared statements in transaction mode, so
            # asyncpg/psycopg prepared statements keep working.
            "MAX_PREPARED_STATEMENTS": "100",
        },
        # The image listens on 5432 inside the container; 6432 is PgBouncer's usual port.
        "ports": ["6432:5432"],
        "depends_on": {"postgres": {"condition": "service_healthy"}},
        "healthcheck": {
            "test": ["CMD", "pg_isready", "-h", "localhost", "-p", "5432"],
            "interval": "10s",
            "timeout": "5s",
            "retries": 5,
        },
    }


PGBOUNCER = ServiceSpec(
    name="pgbouncer",
    description="Connection pooler in front of postgres (transaction mode).",
    image_template="edoburu/pgbouncer:{version}",
    versions=("1.26.0", "1.25.2", "1.24.1"),
    tags={"1.26.0": "v1.26.0-p0", "1.25.2": "v1.25.2-p0", "1.24.1": "v1.24.1-p1"},
    build=_build,
    requires=("postgres",),
)

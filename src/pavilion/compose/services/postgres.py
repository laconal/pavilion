from typing import Any

from pavilion.compose.services.base import ServiceSpec


def _build(version: str) -> dict[str, Any]:
    # Postgres 18+ images keep data in a versioned subdirectory of /var/lib/postgresql;
    # older images declare /var/lib/postgresql/data as the volume.
    data_dir = "/var/lib/postgresql" if int(version) >= 18 else "/var/lib/postgresql/data"
    return {
        "restart": "unless-stopped",
        # Defaults can be overridden from a .env file next to the compose file.
        "environment": {
            "POSTGRES_USER": "${POSTGRES_USER:-postgres}",
            "POSTGRES_PASSWORD": "${POSTGRES_PASSWORD:-postgres}",
            "POSTGRES_DB": "${POSTGRES_DB:-app}",
        },
        "ports": ["5432:5432"],
        "volumes": [f"postgres_data:{data_dir}"],
        "healthcheck": {
            # $$ escapes compose interpolation so the container's env is used.
            "test": ["CMD-SHELL", "pg_isready -U $${POSTGRES_USER} -d $${POSTGRES_DB}"],
            "interval": "10s",
            "timeout": "5s",
            "retries": 5,
        },
    }


POSTGRES = ServiceSpec(
    name="postgres",
    description="PostgreSQL relational database.",
    image_template="postgres:{version}-alpine",
    versions=("18", "17", "16", "15"),
    build=_build,
    volumes={"postgres_data": None},
)

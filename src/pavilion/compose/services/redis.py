from typing import Any

from pavilion.compose.services.base import ServiceSpec


def _build(version: str) -> dict[str, Any]:
    return {
        "restart": "unless-stopped",
        "ports": ["6379:6379"],
        "volumes": ["redis_data:/data"],
        "healthcheck": {
            "test": ["CMD", "redis-cli", "ping"],
            "interval": "10s",
            "timeout": "5s",
            "retries": 5,
        },
    }


REDIS = ServiceSpec(
    name="redis",
    description="In-memory key-value store.",
    image_template="redis:{version}-alpine",
    versions=("8", "7"),
    build=_build,
    volumes={"redis_data": None},
)

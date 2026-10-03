"""Celery worker + beat. They run the project's own code, so they build ./Dockerfile
rather than pulling a public image, and use the compose `redis` service as the broker."""

import re
from typing import Any

WORKER = "celery-worker"
BEAT = "celery-beat"
REQUIRES = ("redis",)
DEFAULT_APP = "app.worker"
DESCRIPTION = "Celery worker + beat, built from ./Dockerfile, Redis as broker."

# What `celery -A` accepts: a module path, optionally `:attribute`.
APP_PATTERN = re.compile(r"[A-Za-z_]\w*(\.[A-Za-z_]\w*)*(:[A-Za-z_]\w*)?")


def celery_services(app: str) -> dict[str, dict[str, Any]]:
    """Compose bodies for the worker and beat services running Celery app `app`."""

    def common() -> dict[str, Any]:
        return {
            "build": ".",
            "restart": "unless-stopped",
            # The app's own settings, if there are any; `environment` below wins over it.
            "env_file": [{"path": ".env", "required": False}],
            "environment": {
                # Celery reads these two directly; no code changes needed.
                "CELERY_BROKER_URL": "redis://redis:6379/0",
                "CELERY_RESULT_BACKEND": "redis://redis:6379/1",
                # Inside the compose network Redis is `redis`, not localhost (.env's value).
                "REDIS_URL": "redis://redis:6379",
            },
            "depends_on": {"redis": {"condition": "service_healthy"}},
        }

    return {
        WORKER: {
            **common(),
            "command": f"celery -A {app} worker --loglevel=info",
            "healthcheck": {
                # $$ escapes compose interpolation: the container's own hostname.
                "test": ["CMD-SHELL", f"celery -A {app} inspect ping -d celery@$$HOSTNAME"],
                "interval": "30s",
                "timeout": "10s",
                "retries": 3,
                "start_period": "20s",
                "start_interval": "5s",  # check often while starting, then every 30s
            },
        },
        # Run exactly one beat, or periodic tasks are sent more than once.
        BEAT: {
            **common(),
            # Keep the schedule state file out of the app directory (bind mounts, read-only).
            "command": f"celery -A {app} beat --loglevel=info --schedule /tmp/celerybeat-schedule",
        },
    }

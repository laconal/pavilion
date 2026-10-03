"""Registry of services pavilion knows how to add to a compose file.

To add a service, create a module next to this one defining a `ServiceSpec`
and list it below.
"""

from pavilion.compose.services.base import ServiceSpec
from pavilion.compose.services.pgbouncer import PGBOUNCER
from pavilion.compose.services.postgres import POSTGRES
from pavilion.compose.services.redis import REDIS

SERVICES: dict[str, ServiceSpec] = {spec.name: spec for spec in [REDIS, POSTGRES, PGBOUNCER]}

__all__ = ["SERVICES", "ServiceSpec"]

from dataclasses import dataclass, field
from typing import Any, Callable


@dataclass(frozen=True)
class ServiceSpec:
    name: str
    description: str
    image_template: str
    # Newest first; the first one is the default.
    versions: tuple[str, ...]
    # Builds the compose service body (everything except `image`) for a version.
    build: Callable[[str], dict[str, Any]]
    volumes: dict[str, Any] = field(default_factory=dict)
    # Other services that must already be in the compose file (e.g. for depends_on).
    requires: tuple[str, ...] = ()
    # Version -> image tag, when tags aren't just the version (e.g. "v1.26.0-p0").
    tags: dict[str, str] = field(default_factory=dict)

    @property
    def default_version(self) -> str:
        return self.versions[0]

    def image(self, version: str) -> str:
        return self.image_template.format(version=self.tags.get(version, version))

    def service(self, version: str) -> dict[str, Any]:
        return {"image": self.image(version), **self.build(version)}

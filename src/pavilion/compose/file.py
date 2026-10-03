"""Reading and writing docker compose files while preserving formatting."""

import re
from pathlib import Path
from typing import Any

from ruamel.yaml import YAML
from ruamel.yaml.comments import CommentedMap, CommentedSeq
from ruamel.yaml.scalarstring import DoubleQuotedScalarString

from pavilion.compose.services import ServiceSpec

# Lookup order used by `docker compose` itself.
COMPOSE_FILENAMES = ("compose.yaml", "compose.yml", "docker-compose.yaml", "docker-compose.yml")
DEFAULT_FILENAME = "docker-compose.yml"

# e.g. "6379:6379", "127.0.0.1:8080:80", "53:53/udp"
PORT_MAPPING = re.compile(r"[\d.:-]+(/(tcp|udp))?")


class ServiceExistsError(Exception):
    pass


def find_compose_file(directory: Path) -> Path:
    """Return the existing compose file in `directory`, or the default path to create."""
    for name in COMPOSE_FILENAMES:
        candidate = directory / name
        if candidate.is_file():
            return candidate
    return directory / DEFAULT_FILENAME


def _yaml() -> YAML:
    yaml = YAML()
    yaml.indent(mapping=2, sequence=4, offset=2)
    yaml.preserve_quotes = True
    # Never fold long values (e.g. connection URLs) onto a continuation line.
    yaml.width = 4096
    return yaml


def _to_yaml_node(value: Any) -> Any:
    """Convert plain data into ruamel nodes with compose-friendly styling."""
    if isinstance(value, dict):
        node = CommentedMap()
        for key, item in value.items():
            node[key] = _to_yaml_node(item)
        return node
    if isinstance(value, list):
        seq = CommentedSeq(_to_yaml_node(item) for item in value)
        # Short exec-form lists like healthcheck tests read best inline.
        if value and value[0] in ("CMD", "CMD-SHELL"):
            seq.fa.set_flow_style()
        return seq
    if isinstance(value, str) and PORT_MAPPING.fullmatch(value):
        # Unquoted "6379:6379" is a base-60 integer to YAML 1.1 parsers.
        return DoubleQuotedScalarString(value)
    return value


def _load(yaml: YAML, path: Path) -> CommentedMap:
    data = yaml.load(path) if path.exists() else None
    return CommentedMap() if data is None else data


def has_service(path: Path, name: str) -> bool:
    return name in (_load(_yaml(), path).get("services") or {})


def add_service(path: Path, spec: ServiceSpec, version: str, *, force: bool = False) -> None:
    yaml = _yaml()
    data = _load(yaml, path)

    # `services:` with no entries loads as None, so treat it like a missing key.
    if data.get("services") is None:
        data["services"] = CommentedMap()
    services = data["services"]
    if spec.name in services and not force:
        raise ServiceExistsError(spec.name)
    services[spec.name] = _to_yaml_node(spec.service(version))

    if spec.volumes:
        if data.get("volumes") is None:
            data["volumes"] = CommentedMap()
        volumes = data["volumes"]
        for name, config in spec.volumes.items():
            if name not in volumes:
                volumes[name] = _to_yaml_node(config)

    yaml.dump(data, path)

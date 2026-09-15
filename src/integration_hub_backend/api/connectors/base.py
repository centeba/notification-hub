"""Pluggable connector framework (claims-platform A4 gaps).

Layers a typed contract over the DB-backed inbound connector registry:

  - ``PluggableConnectorBase`` — the connector interface: a JSON-Schema
    ``payload_schema`` for the inbound vendor payload, ``validate()``, and
    ``transform()`` (vendor → canonical).
  - ``FieldMapConnector`` — the DEFAULT implementation for declarative
    (``field_map``) connectors, so every connector — declarative or code — runs
    through the same validate → transform pipeline.
  - a registry so a connector key needing custom logic (nested extraction,
    computed fields, vendor quirks) can register a code subclass that overrides
    ``transform``; the ingest service prefers it over the field_map default.

Validation uses JSON Schema (``jsonschema``) and is enforced at ingest both on
the inbound payload (against the connector's ``payload_schema``) and on the
canonical output (against the target event type's ``payload_schema``).
"""

from typing import Any

import jsonschema


class ConnectorValidationError(Exception):
    """Inbound payload or canonical output failed schema validation (→ HTTP 422)."""

    def __init__(self, message: str, errors: list[dict[str, Any]] | None = None) -> None:
        super().__init__(message)
        self.errors = errors or []


def validate_against_schema(
    data: Any, schema: dict[str, Any] | None, *, what: str = "payload"
) -> None:
    """Validate ``data`` against a JSON Schema. No-op when ``schema`` is falsy."""
    if not schema:
        return
    try:
        jsonschema.validate(instance=data, schema=schema)
    except jsonschema.ValidationError as exc:
        raise ConnectorValidationError(
            f"{what} failed schema validation: {exc.message}",
            errors=[{"path": list(exc.absolute_path), "message": exc.message}],
        ) from exc
    except jsonschema.SchemaError as exc:
        # A bad schema is a config error, not the caller's fault — surface clearly.
        raise ConnectorValidationError(f"{what} schema is invalid: {exc.message}") from exc


def dig(payload: Any, path: str) -> Any:
    """Extract a dot-path value from a nested dict (``a.b.c``)."""
    cur = payload
    for part in path.split("."):
        if isinstance(cur, dict) and part in cur:
            cur = cur[part]
        else:
            return None
    return cur


class PluggableConnectorBase:
    """Base connector contract. Subclass + ``register_connector`` for custom
    transform logic; otherwise ``FieldMapConnector`` is used automatically."""

    key: str = ""
    payload_schema: dict[str, Any] | None = None

    def validate(self, payload: dict[str, Any]) -> None:
        validate_against_schema(payload, self.payload_schema, what="inbound payload")

    def transform(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Vendor payload → canonical event payload. Default is identity."""
        return dict(payload)


class FieldMapConnector(PluggableConnectorBase):
    """Default connector built from a registry row's ``field_map`` (dot-path
    extraction) + optional ``payload_schema``."""

    def __init__(
        self,
        key: str,
        field_map: dict[str, Any] | None,
        payload_schema: dict[str, Any] | None = None,
    ) -> None:
        self.key = key
        self.field_map = field_map or {}
        self.payload_schema = payload_schema

    def transform(self, payload: dict[str, Any]) -> dict[str, Any]:
        if not self.field_map:
            return dict(payload)
        return {
            cf: dig(payload, sp)
            for cf, sp in self.field_map.items()
            if dig(payload, sp) is not None
        }


_REGISTRY: dict[str, PluggableConnectorBase] = {}


def register_connector(instance: PluggableConnectorBase) -> PluggableConnectorBase:
    """Register a code connector instance under its ``key``."""
    if not instance.key:
        raise ValueError("connector instance must set a non-empty .key")
    _REGISTRY[instance.key] = instance
    return instance


def get_connector(key: str) -> PluggableConnectorBase | None:
    """A registered code connector for ``key``, or None (→ use FieldMapConnector)."""
    return _REGISTRY.get(key)

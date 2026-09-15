"""Inbound connector service — generic claims/FNOL gateway (claims-platform A4).

DB-backed: connectors are rows in ``inbound_connectors`` (per-company runtime
config — adding a carrier feed = a row, via the admin endpoints, no deploy).
Shared by the HTTP route and the MCP tool surface. Per ingest: publishes a
canonical event on the notification bus AND forwards the FNOL to the owning
vertical app (restoration's ``/intake/{key}``), which maps it + creates the
pending project.
"""

import os
import uuid
from typing import Any

import httpx
import structlog
from sqlalchemy import select

from integration_hub_backend.api.connectors.base import (
    FieldMapConnector,
    get_connector,
    validate_against_schema,
)
from integration_hub_backend.api.core.db import AsyncSessionLocal
from integration_hub_backend.api.models.event_type import NotificationEventType
from integration_hub_backend.api.models.inbound_connector import InboundConnector
from integration_hub_backend.api.temporal.activities.dispatch import EventInput
from integration_hub_backend.api.temporal.client import get_temporal_client
from integration_hub_backend.api.temporal.workflows.notification_dispatch import (
    TASK_QUEUE,
    NotificationDispatchWorkflow,
)

log = structlog.get_logger(__name__)

_INTERNAL_KEY = (
    os.environ.get("INTERNAL_API_KEY") or os.environ.get("INTERNAL_SERVICE_SECRET") or ""
)


def _dig(payload: Any, path: str) -> Any:
    cur = payload
    for part in path.split("."):
        if isinstance(cur, dict) and part in cur:
            cur = cur[part]
        else:
            return None
    return cur


class ConnectorNotFound(Exception):
    """Raised when an unknown/inactive connector key is requested."""


class ConnectorService:
    def __init__(self, db: Any = None) -> None:
        self.db = db  # accepted for parity with other MCP services; unused

    async def list_connectors(self) -> dict[str, Any]:
        async with AsyncSessionLocal() as db:
            rows = (
                (
                    await db.execute(
                        select(InboundConnector).where(InboundConnector.is_active.is_(True))
                    )
                )
                .scalars()
                .all()
            )
        return {
            "connectors": [
                {
                    "key": r.key,
                    "label": r.label,
                    "company_id": str(r.company_id) if r.company_id else None,
                    "event_type": r.event_type,
                    "forward": r.forward_url,
                }
                for r in rows
            ]
        }

    async def ingest(
        self,
        connector_key: str,
        payload: dict[str, Any],
        company_id: uuid.UUID | str | None = None,
    ) -> dict[str, Any]:
        async with AsyncSessionLocal() as db:
            spec = (
                await db.execute(
                    select(InboundConnector).where(
                        InboundConnector.key == connector_key,
                        InboundConnector.is_active.is_(True),
                    )
                )
            ).scalar_one_or_none()
            if spec is None:
                raise ConnectorNotFound(f"unknown connector '{connector_key}'")
            # Capture while attached; the target event type's schema gives us
            # canonical typing.
            spec_company_id = spec.company_id
            spec_event_type = spec.event_type
            spec_field_map = spec.field_map or {}
            spec_payload_schema = spec.payload_schema
            spec_forward_url = spec.forward_url
            et = (
                await db.execute(
                    select(NotificationEventType).where(
                        NotificationEventType.name == spec_event_type
                    )
                )
            ).scalar_one_or_none()
            event_schema = et.payload_schema if et else None

        # Connector-owned company wins; else the caller-provided one.
        company = (
            str(spec_company_id) if spec_company_id else (str(company_id) if company_id else "")
        )

        # Resolve the connector impl: a registered code connector (custom
        # transform) wins; otherwise the declarative field_map connector. Both
        # run the same validate → transform pipeline (A4 gap: PluggableConnectorBase).
        impl = get_connector(connector_key) or FieldMapConnector(
            connector_key, spec_field_map, spec_payload_schema
        )
        # 1) Validate the inbound vendor payload (raises ConnectorValidationError
        #    → HTTP 422). 2) Transform to canonical. 3) Validate the canonical
        #    output against the event type's declared schema (canonical typing).
        impl.validate(payload)
        canonical = impl.transform(payload)
        validate_against_schema(canonical, event_schema, what="canonical event")

        event_id = str(uuid.uuid4())

        published = False
        try:
            temporal = await get_temporal_client()
            await temporal.start_workflow(
                NotificationDispatchWorkflow.run,
                EventInput(
                    event_id=event_id,
                    event_type=spec_event_type,
                    company_id=company,
                    payload=canonical,
                ),
                id=f"connector-{event_id}",
                task_queue=TASK_QUEUE,
            )
            published = True
        except Exception as exc:  # noqa: BLE001
            log.warning("connector_event_publish_failed", connector=connector_key, error=str(exc))

        forwarded = False
        ds_status: int | None = None
        ds_body: dict[str, Any] | None = None
        if spec_forward_url:
            headers = {"Content-Type": "application/json"}
            if _INTERNAL_KEY:
                headers["X-Internal-Key"] = _INTERNAL_KEY
            if company:
                headers["X-Company-Id"] = company
            try:
                async with httpx.AsyncClient(timeout=10) as client:
                    resp = await client.post(spec_forward_url, json=payload, headers=headers)
                    ds_status = resp.status_code
                    try:
                        ds_body = resp.json()
                    except Exception:  # noqa: BLE001
                        ds_body = None
                    forwarded = True
            except Exception as exc:  # noqa: BLE001
                log.warning(
                    "connector_forward_failed",
                    connector=connector_key,
                    url=spec_forward_url,
                    error=str(exc),
                )

        return {
            "connector": connector_key,
            "event_id": event_id,
            "event_published": published,
            "forwarded": forwarded,
            "downstream_status": ds_status,
            "downstream_body": ds_body,
        }

    # ── Admin registry management (A4) ────────────────────────────────────────

    async def create_connector(self, data: dict[str, Any]) -> InboundConnector:
        async with AsyncSessionLocal() as db:
            row = InboundConnector(
                key=data["key"],
                label=data["label"],
                company_id=data.get("company_id"),
                event_type=data.get("event_type") or "claim.assigned",
                forward_url=data.get("forward_url"),
                field_map=data.get("field_map") or {},
                payload_schema=data.get("payload_schema"),
                is_active=data.get("is_active", True),
            )
            db.add(row)
            await db.commit()
            await db.refresh(row)
            return row

    async def list_all(self) -> list[InboundConnector]:
        async with AsyncSessionLocal() as db:
            return list(
                (await db.execute(select(InboundConnector).order_by(InboundConnector.key)))
                .scalars()
                .all()
            )

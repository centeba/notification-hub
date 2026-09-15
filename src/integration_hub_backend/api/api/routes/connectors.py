"""Inbound connector ingestion — generic claims/FNOL gateway (claims-platform A4).

A carrier/TPA posts an FNOL to ``POST /api/v1/connectors/{key}/ingest``. The
declarative connector spec (config, not per-carrier code) publishes a canonical
``claim.assigned`` event onto the notification bus AND forwards the FNOL to the
owning vertical app (restoration's ``/intake/{key}``), which maps it + creates
the pending project in the assignment queue. M2M auth via ``X-Internal-Key`` /
Bearer ``INTERNAL_SERVICE_SECRET``.

The logic lives in ``services/connector_service.py`` so the MCP tool surface
drives the exact same path.
"""

from typing import Any

from fastapi import APIRouter, Body, Depends, Header, HTTPException, status
from pydantic import BaseModel

from integration_hub_backend.api.api.deps import require_internal_service
from integration_hub_backend.api.connectors.base import ConnectorValidationError
from integration_hub_backend.api.models.inbound_connector import (
    InboundConnectorCreate,
    InboundConnectorPublic,
)
from integration_hub_backend.api.services.connector_service import (
    ConnectorNotFound,
    ConnectorService,
)

router = APIRouter(prefix="/connectors", tags=["connectors"])


@router.post(
    "",
    response_model=InboundConnectorPublic,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_internal_service)],
)
async def create_connector(body: InboundConnectorCreate) -> InboundConnectorPublic:
    """Register a per-company inbound connector (A4 — runtime config, no deploy)."""
    row = await ConnectorService().create_connector(body.model_dump())
    return InboundConnectorPublic.model_validate(row)


@router.get(
    "/all",
    response_model=list[InboundConnectorPublic],
    dependencies=[Depends(require_internal_service)],
)
async def list_all_connectors() -> list[InboundConnectorPublic]:
    """List ALL connectors (incl. inactive) for admin."""
    rows = await ConnectorService().list_all()
    return [InboundConnectorPublic.model_validate(r) for r in rows]


class ConnectorIngestResponse(BaseModel):
    connector: str
    event_id: str
    event_published: bool
    forwarded: bool
    downstream_status: int | None = None
    downstream_body: dict[str, Any] | None = None


@router.get("", dependencies=[Depends(require_internal_service)])
async def list_connectors() -> dict[str, Any]:
    """List the configured inbound connectors (registry surface)."""
    return await ConnectorService().list_connectors()


@router.post(
    "/{connector_key}/ingest",
    response_model=ConnectorIngestResponse,
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(require_internal_service)],
)
async def ingest_connector(
    connector_key: str,
    payload: dict[str, Any] = Body(...),
    x_company_id: str | None = Header(default=None, alias="X-Company-Id"),
) -> ConnectorIngestResponse:
    """Ingest a vendor FNOL: publish a canonical event + forward downstream."""
    try:
        result = await ConnectorService().ingest(connector_key, payload, company_id=x_company_id)
    except ConnectorNotFound as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    except ConnectorValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"message": str(exc), "errors": exc.errors},
        )
    return ConnectorIngestResponse(**result)

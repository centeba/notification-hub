"""Splunk HEC integration - event shipping (Global)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel

from integration_hub_backend.api.api.deps import ApiKeyDep, SessionDep
from integration_hub_backend.api.services.observability_service import ObservabilityService

router = APIRouter(prefix="/splunk", tags=["integrations"])


class SplunkEventRequest(BaseModel):
    event: dict[str, Any]
    index: str | None = None
    sourcetype: str | None = None


@router.post("/event")
async def send_splunk_event(
    body: SplunkEventRequest, db: SessionDep, api_key: ApiKeyDep
) -> dict[str, Any]:
    """Trigger a Temporal workflow to send an event to Splunk (Global)."""
    api_key.require_scope("integrations:splunk")

    service = ObservabilityService(db)
    run_id = await service.push_data(
        integration_type="splunk",
        operation="send_event",
        data=body.model_dump(),
        company_id=api_key.company_id,
    )
    return {"status": "queued", "run_id": run_id}

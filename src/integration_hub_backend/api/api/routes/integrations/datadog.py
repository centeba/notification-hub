"""Datadog integration - events and logs (Global)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel, Field

from integration_hub_backend.api.api.deps import ApiKeyDep, SessionDep
from integration_hub_backend.api.services.observability_service import ObservabilityService

router = APIRouter(prefix="/datadog", tags=["integrations"])


class DatadogEventRequest(BaseModel):
    title: str
    text: str
    priority: str = "normal"  # normal | low
    alert_type: str = "info"  # error | warning | info | success
    tags: list[str] = Field(default_factory=list)


class DatadogLogRequest(BaseModel):
    message: str
    service: str = "integration-hub"
    ddsource: str = "python"
    tags: list[str] = Field(default_factory=list)


@router.post("/event")
async def send_datadog_event(
    body: DatadogEventRequest, db: SessionDep, api_key: ApiKeyDep
) -> dict[str, Any]:
    """Trigger a Temporal workflow to send an event to Datadog (Global)."""
    api_key.require_scope("integrations:datadog")

    service = ObservabilityService(db)
    run_id = await service.push_data(
        integration_type="datadog",
        operation="send_event",
        data=body.model_dump(),
        company_id=api_key.company_id,
    )
    return {"status": "queued", "run_id": run_id}


@router.post("/log")
async def send_datadog_log(
    body: DatadogLogRequest, db: SessionDep, api_key: ApiKeyDep
) -> dict[str, Any]:
    """Trigger a Temporal workflow to send a log to Datadog (Global)."""
    api_key.require_scope("integrations:datadog")

    service = ObservabilityService(db)
    run_id = await service.push_data(
        integration_type="datadog",
        operation="send_log",
        data=body.model_dump(),
        company_id=api_key.company_id,
    )
    return {"status": "queued", "run_id": run_id}

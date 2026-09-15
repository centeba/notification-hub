"""Grafana integration - creating annotations (Global)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel, Field

from integration_hub_backend.api.api.deps import ApiKeyDep, SessionDep
from integration_hub_backend.api.services.observability_service import ObservabilityService

router = APIRouter(prefix="/grafana", tags=["integrations"])


class GrafanaAnnotationRequest(BaseModel):
    text: str
    tags: list[str] = Field(default_factory=list)
    time: int | None = None
    time_end: int | None = None


@router.post("/annotation")
async def create_grafana_annotation(
    body: GrafanaAnnotationRequest, db: SessionDep, api_key: ApiKeyDep
) -> dict[str, Any]:
    """Trigger a Temporal workflow to create a Grafana annotation (Global)."""
    api_key.require_scope("integrations:grafana")

    service = ObservabilityService(db)
    run_id = await service.push_data(
        integration_type="grafana",
        operation="create_annotation",
        data=body.model_dump(),
        company_id=api_key.company_id,
    )
    return {"status": "queued", "run_id": run_id}

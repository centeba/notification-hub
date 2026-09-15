"""Elasticsearch integration - indexing documents (Global)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel

from integration_hub_backend.api.api.deps import ApiKeyDep, SessionDep
from integration_hub_backend.api.services.observability_service import ObservabilityService

router = APIRouter(prefix="/elasticsearch", tags=["integrations"])


class ElasticsearchIndexRequest(BaseModel):
    index: str = "logs"
    document: dict[str, Any]


@router.post("/index")
async def index_document_elasticsearch(
    body: ElasticsearchIndexRequest, db: SessionDep, api_key: ApiKeyDep
) -> dict[str, Any]:
    """Trigger a Temporal workflow to index a document in Elasticsearch (Global)."""
    api_key.require_scope("integrations:elasticsearch")

    service = ObservabilityService(db)
    run_id = await service.push_data(
        integration_type="elasticsearch",
        operation="index_document",
        data=body.model_dump(),
        company_id=api_key.company_id,
    )
    return {"status": "queued", "run_id": run_id}

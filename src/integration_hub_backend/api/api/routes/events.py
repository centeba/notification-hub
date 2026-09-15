"""Event ingestion endpoint — receives events and triggers Temporal dispatch workflow."""

from __future__ import annotations

import uuid
from typing import Any

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, field_validator

from integration_hub_backend.api.api.deps import (
    ApiKeyDep,
    RedisDep,
    SessionDep,
    optional_webhook_signature,
)
from integration_hub_backend.api.core.limiter import limiter
from integration_hub_backend.api.temporal.activities.dispatch import EventInput
from integration_hub_backend.api.temporal.client import get_temporal_client
from integration_hub_backend.api.temporal.workflows.notification_dispatch import (
    TASK_QUEUE,
    NotificationDispatchWorkflow,
)

log = structlog.get_logger(__name__)
router = APIRouter(prefix="/events", tags=["events"])


class EventIngestRequest(BaseModel):
    event_type: str
    payload: dict[str, Any] = {}
    # Optional idempotency key — used as Temporal workflow ID for dedup
    idempotency_key: str | None = None

    @field_validator("event_type")
    @classmethod
    def validate_event_type(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("event_type cannot be empty")
        if len(v) > 100:
            raise ValueError("event_type too long (max 100 chars)")
        return v


class EventIngestResponse(BaseModel):
    event_id: str
    workflow_id: str
    status: str


@router.post(
    "/ingest",
    response_model=EventIngestResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Ingest a notification event",
    description=(
        "Receive an event and asynchronously dispatch notifications according to "
        "matching rules. Requires an API key with the 'notify:send' scope. When "
        "WEBHOOK_SECRET is configured, a valid X-Hub-Signature-256 (+ optional "
        "X-Sentinel-Timestamp) is required as a second factor."
    ),
    # Optional inbound-webhook HMAC — enforced only when WEBHOOK_SECRET is set,
    # otherwise a no-op (API-key auth unchanged). Runs before the handler.
    dependencies=[Depends(optional_webhook_signature)],
)
@limiter.limit("100/minute")
async def ingest_event(
    request: Request,
    body: EventIngestRequest,
    api_key: ApiKeyDep,
    db: SessionDep,
    redis: RedisDep,
) -> EventIngestResponse:
    api_key.require_scope("notify:send")

    event_id = str(uuid.uuid4())
    workflow_id = body.idempotency_key or f"notif-{event_id}"

    event = EventInput(
        event_id=event_id,
        event_type=body.event_type,
        company_id=str(api_key.company_id),
        payload=body.payload,
    )

    try:
        temporal = await get_temporal_client()
        await temporal.start_workflow(
            NotificationDispatchWorkflow.run,
            event,
            id=workflow_id,
            task_queue=TASK_QUEUE,
        )
    except Exception as e:
        log.error("workflow_start_failed", event_id=event_id, error=str(e))
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Failed to start notification workflow. Please retry.",
        )

    log.info(
        "event_ingested", event_id=event_id, event_type=body.event_type, workflow_id=workflow_id
    )
    return EventIngestResponse(
        event_id=event_id,
        workflow_id=workflow_id,
        status="accepted",
    )

"""Delivery log query endpoints."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Query

from integration_hub_backend.api.api.deps import CurrentUser, SessionDep
from integration_hub_backend.api.crud.delivery_logs import list_delivery_logs
from integration_hub_backend.api.models.delivery_log import (
    DeliveryLogPublic,
    DeliveryLogsPublic,
    DeliveryStatus,
)

router = APIRouter(prefix="/logs", tags=["logs"])


@router.get("", response_model=DeliveryLogsPublic)
async def get_delivery_logs(
    current_user: CurrentUser,
    db: SessionDep,
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    event_type: str | None = None,
    channel: str | None = None,
    status_filter: DeliveryStatus | None = Query(None, alias="status"),
    recipient_user_id: uuid.UUID | None = None,
) -> DeliveryLogsPublic:
    # Users can only see their own logs; admins see all company logs
    filter_user_id = None if current_user.is_company_admin else current_user.user_id
    if recipient_user_id and not current_user.is_company_admin:
        filter_user_id = current_user.user_id  # Non-admins always filtered to self

    logs, count = await list_delivery_logs(
        db,
        company_id=current_user.company_id,
        skip=skip,
        limit=limit,
        event_type=event_type,
        channel=channel,
        status=status_filter,
        recipient_user_id=filter_user_id or recipient_user_id,
    )
    return DeliveryLogsPublic(
        data=[DeliveryLogPublic.model_validate(lg) for lg in logs],
        count=count,
    )

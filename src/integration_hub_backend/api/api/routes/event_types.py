"""Notification event-type listing endpoint.

Read-only list of the event types a rule can subscribe to. Returns the
platform-global types (``company_id IS NULL``) plus any defined for the
caller's own company. Used by the Notification Hub rule editor to populate
the event dropdown.
"""

from fastapi import APIRouter
from sqlalchemy import ColumnElement, or_, select

from integration_hub_backend.api.api.deps import CurrentUser, SessionDep
from integration_hub_backend.api.models.event_type import (
    EventTypePublic,
    EventTypesPublic,
    NotificationEventType,
)

router = APIRouter(prefix="/event-types", tags=["event-types"])


@router.get("", response_model=EventTypesPublic)
async def list_event_types(
    current_user: CurrentUser,
    db: SessionDep,
) -> EventTypesPublic:
    # Global event types (company_id IS NULL) are visible to everyone; a
    # company also sees any it defines for itself.
    conds: list[ColumnElement[bool]] = [NotificationEventType.company_id.is_(None)]
    if current_user.company_id is not None:
        conds.append(NotificationEventType.company_id == current_user.company_id)
    result = await db.execute(
        select(NotificationEventType)
        .where(
            NotificationEventType.is_active == True,  # noqa: E712
            or_(*conds),
        )
        .order_by(NotificationEventType.name)
    )
    rows = list(result.scalars().all())
    return EventTypesPublic(
        data=[EventTypePublic.model_validate(r) for r in rows],
        count=len(rows),
    )

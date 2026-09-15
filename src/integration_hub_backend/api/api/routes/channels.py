"""Notification channels listing endpoint."""

from __future__ import annotations

from fastapi import APIRouter
from sqlalchemy import select

from integration_hub_backend.api.api.deps import CurrentUser, SessionDep
from integration_hub_backend.api.models.channel import (
    ChannelPublic,
    ChannelsPublic,
    NotificationChannel,
)

router = APIRouter(prefix="/channels", tags=["channels"])


@router.get("", response_model=ChannelsPublic)
async def list_channels(
    current_user: CurrentUser,
    db: SessionDep,
) -> ChannelsPublic:
    result = await db.execute(
        select(NotificationChannel).where(NotificationChannel.is_active == True)  # noqa: E712
    )
    channels = list(result.scalars().all())
    return ChannelsPublic(
        data=[ChannelPublic.model_validate(c) for c in channels],
        count=len(channels),
    )

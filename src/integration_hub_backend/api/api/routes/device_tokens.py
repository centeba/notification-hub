"""Device-token registration for push notifications (A8).

A client registers a device/browser push token here; send_push_activity fans a
push out to all active tokens for a recipient. M2M-authed (the vertical app /
mobile backend registers on the user's behalf); upserts on (platform, token).
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, status
from sqlalchemy import select

from integration_hub_backend.api.api.deps import SessionDep, require_internal_service
from integration_hub_backend.api.models.device_token import (
    DeviceToken,
    DeviceTokenPublic,
    DeviceTokenRegister,
)

router = APIRouter(prefix="/device-tokens", tags=["device-tokens"])


@router.post(
    "",
    response_model=DeviceTokenPublic,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_internal_service)],
)
async def register_device(body: DeviceTokenRegister, db: SessionDep) -> DeviceTokenPublic:
    existing = (
        await db.execute(
            select(DeviceToken).where(
                DeviceToken.platform == body.platform,
                DeviceToken.token == body.token,
            )
        )
    ).scalar_one_or_none()
    if existing:
        existing.user_id = body.user_id
        existing.company_id = body.company_id
        existing.is_active = True
        await db.commit()
        await db.refresh(existing)
        return DeviceTokenPublic.model_validate(existing)
    row = DeviceToken(**body.model_dump())
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return DeviceTokenPublic.model_validate(row)


@router.get(
    "",
    response_model=list[DeviceTokenPublic],
    dependencies=[Depends(require_internal_service)],
)
async def list_devices(user_id: uuid.UUID, db: SessionDep) -> list[DeviceTokenPublic]:
    rows = (
        (
            await db.execute(
                select(DeviceToken).where(
                    DeviceToken.user_id == user_id,
                    DeviceToken.is_active.is_(True),
                )
            )
        )
        .scalars()
        .all()
    )
    return [DeviceTokenPublic.model_validate(r) for r in rows]


@router.delete(
    "/{token_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_internal_service)],
)
async def deactivate_device(token_id: uuid.UUID, db: SessionDep) -> None:
    row = (
        await db.execute(select(DeviceToken).where(DeviceToken.id == token_id))
    ).scalar_one_or_none()
    if row:
        row.is_active = False
        await db.commit()

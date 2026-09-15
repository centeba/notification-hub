"""User and company notification preferences endpoints."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select

from integration_hub_backend.api.api.deps import CompanyAdminDep, CurrentUser, RedisDep, SessionDep
from integration_hub_backend.api.core.cache import _key_user_preferences, cache_delete
from integration_hub_backend.api.models.preference import (
    NotificationPreference,
    PreferencePublic,
    PreferencesPublic,
    PreferenceUpsert,
)

router = APIRouter(prefix="/preferences", tags=["preferences"])


@router.get("/me", response_model=PreferencesPublic)
async def get_my_preferences(
    current_user: CurrentUser,
    db: SessionDep,
) -> PreferencesPublic:
    result = await db.execute(
        select(NotificationPreference).where(
            NotificationPreference.user_id == current_user.user_id,
            NotificationPreference.company_id == current_user.company_id,
        )
    )
    prefs = list(result.scalars().all())
    return PreferencesPublic(data=[PreferencePublic.model_validate(p) for p in prefs])


@router.put("/me/{channel_id}", response_model=PreferencePublic)
async def upsert_my_preference(
    channel_id: uuid.UUID,
    body: PreferenceUpsert,
    current_user: CurrentUser,
    db: SessionDep,
    redis: RedisDep,
) -> PreferencePublic:
    if current_user.company_id is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="No company")

    result = await db.execute(
        select(NotificationPreference).where(
            NotificationPreference.user_id == current_user.user_id,
            NotificationPreference.company_id == current_user.company_id,
            NotificationPreference.channel_id == channel_id,
        )
    )
    pref = result.scalar_one_or_none()

    if pref:
        pref.is_enabled = body.is_enabled
        pref.language = body.language
        pref.quiet_hours_start = body.quiet_hours_start
        pref.quiet_hours_end = body.quiet_hours_end
        pref.timezone = body.timezone
    else:
        pref = NotificationPreference(
            user_id=current_user.user_id,
            company_id=current_user.company_id,
            channel_id=channel_id,
            is_enabled=body.is_enabled,
            language=body.language,
            quiet_hours_start=body.quiet_hours_start,
            quiet_hours_end=body.quiet_hours_end,
            timezone=body.timezone,
        )
        db.add(pref)

    await db.commit()
    await db.refresh(pref)
    await cache_delete(redis, _key_user_preferences(str(current_user.user_id)))
    return PreferencePublic.model_validate(pref)


@router.get("/company", response_model=PreferencesPublic)
async def get_company_preferences(
    current_user: CompanyAdminDep,
    db: SessionDep,
) -> PreferencesPublic:
    if current_user.company_id is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="No company")
    result = await db.execute(
        select(NotificationPreference).where(
            NotificationPreference.user_id.is_(None),
            NotificationPreference.company_id == current_user.company_id,
        )
    )
    prefs = list(result.scalars().all())
    return PreferencesPublic(data=[PreferencePublic.model_validate(p) for p in prefs])


@router.put("/company/{channel_id}", response_model=PreferencePublic)
async def upsert_company_preference(
    channel_id: uuid.UUID,
    body: PreferenceUpsert,
    current_user: CompanyAdminDep,
    db: SessionDep,
) -> PreferencePublic:
    if current_user.company_id is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="No company")

    result = await db.execute(
        select(NotificationPreference).where(
            NotificationPreference.user_id.is_(None),
            NotificationPreference.company_id == current_user.company_id,
            NotificationPreference.channel_id == channel_id,
        )
    )
    pref = result.scalar_one_or_none()

    if pref:
        pref.is_enabled = body.is_enabled
        pref.language = body.language
        pref.quiet_hours_start = body.quiet_hours_start
        pref.quiet_hours_end = body.quiet_hours_end
        pref.timezone = body.timezone
    else:
        pref = NotificationPreference(
            user_id=None,
            company_id=current_user.company_id,
            channel_id=channel_id,
            is_enabled=body.is_enabled,
            language=body.language,
            quiet_hours_start=body.quiet_hours_start,
            quiet_hours_end=body.quiet_hours_end,
            timezone=body.timezone,
        )
        db.add(pref)

    await db.commit()
    await db.refresh(pref)
    return PreferencePublic.model_validate(pref)

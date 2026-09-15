"""Company settings endpoints."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, status

from integration_hub_backend.api.api.deps import (
    CompanyAdminDep,
    RedisDep,
    SessionDep,
)
from integration_hub_backend.api.core.cache import _key_company_settings, cache_delete
from integration_hub_backend.api.crud.company_settings import (
    get_company_settings,
    set_sms_provider_config,
    update_company_settings,
    upsert_company_settings,
)
from integration_hub_backend.api.models.company_settings import (
    CompanySettingsCreate,
    CompanySettingsPublic,
    CompanySettingsUpdate,
)

router = APIRouter(prefix="/company-settings", tags=["company-settings"])


@router.get("/me", response_model=CompanySettingsPublic)
async def get_my_company_settings(
    current_user: CompanyAdminDep,
    db: SessionDep,
) -> CompanySettingsPublic:
    if current_user.company_id is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="No company")
    settings = await get_company_settings(db, current_user.company_id)
    if not settings:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Company settings not found"
        )
    return CompanySettingsPublic.model_validate(settings)


@router.post("/me", response_model=CompanySettingsPublic, status_code=status.HTTP_201_CREATED)
async def create_my_company_settings(
    body: CompanySettingsCreate,
    current_user: CompanyAdminDep,
    db: SessionDep,
    redis: RedisDep,
) -> CompanySettingsPublic:
    if current_user.company_id is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="No company")
    # Enforce company_id from authenticated context
    body.company_id = current_user.company_id
    settings = await upsert_company_settings(db, body)
    await cache_delete(redis, _key_company_settings(str(current_user.company_id)))
    return CompanySettingsPublic.model_validate(settings)


@router.patch("/me", response_model=CompanySettingsPublic)
async def update_my_company_settings(
    body: CompanySettingsUpdate,
    current_user: CompanyAdminDep,
    db: SessionDep,
    redis: RedisDep,
) -> CompanySettingsPublic:
    if current_user.company_id is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="No company")
    settings_obj = await get_company_settings(db, current_user.company_id)
    if not settings_obj:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Company settings not found"
        )
    updated = await update_company_settings(db, settings_obj, body)
    await cache_delete(redis, _key_company_settings(str(current_user.company_id)))
    return CompanySettingsPublic.model_validate(updated)


@router.post("/me/sms-provider-config", status_code=status.HTTP_204_NO_CONTENT)
async def set_my_sms_provider_config(
    body: dict[str, Any],
    current_user: CompanyAdminDep,
    db: SessionDep,
) -> None:
    """
    Store SMS provider credentials (encrypted at rest).
    Body should be provider-specific:
    - Twilio: {"account_sid": "...", "auth_token": "...", "from_number": "..."}
    - AWS SNS: {"access_key_id": "...", "secret_access_key": "...", "region": "..."}
    """
    if current_user.company_id is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="No company")
    settings_obj = await get_company_settings(db, current_user.company_id)
    if not settings_obj:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Company settings not found"
        )
    await set_sms_provider_config(db, settings_obj, body)

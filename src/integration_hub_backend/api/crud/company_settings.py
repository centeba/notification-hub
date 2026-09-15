"""CRUD operations for company settings."""

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from integration_hub_backend.api.core.security import decrypt_field, encrypt_field
from integration_hub_backend.api.models.company_settings import (
    CompanySettingsCreate,
    CompanySettingsUpdate,
    NotificationCompanySettings,
)


async def get_company_settings(
    db: AsyncSession, company_id: uuid.UUID
) -> NotificationCompanySettings | None:
    result = await db.execute(
        select(NotificationCompanySettings).where(
            NotificationCompanySettings.company_id == company_id
        )
    )
    return result.scalar_one_or_none()


async def create_company_settings(
    db: AsyncSession, data: CompanySettingsCreate
) -> NotificationCompanySettings:
    settings = NotificationCompanySettings(
        company_id=data.company_id,
        default_language=data.default_language,
        sms_provider=data.sms_provider,
        email_from_address=data.email_from_address,
        email_from_name=data.email_from_name,
        max_notifications_per_day=data.max_notifications_per_day,
    )
    db.add(settings)
    await db.commit()
    await db.refresh(settings)
    return settings


async def update_company_settings(
    db: AsyncSession,
    settings_obj: NotificationCompanySettings,
    data: CompanySettingsUpdate,
) -> NotificationCompanySettings:
    update_data = data.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(settings_obj, field, value)
    await db.commit()
    await db.refresh(settings_obj)
    return settings_obj


async def upsert_company_settings(
    db: AsyncSession, data: CompanySettingsCreate
) -> NotificationCompanySettings:
    existing = await get_company_settings(db, data.company_id)
    if existing:
        update_data = CompanySettingsUpdate(**data.model_dump(exclude={"company_id"}))
        return await update_company_settings(db, existing, update_data)
    return await create_company_settings(db, data)


async def set_sms_provider_config(
    db: AsyncSession,
    settings_obj: NotificationCompanySettings,
    config: dict[str, Any],
) -> NotificationCompanySettings:
    """Store SMS provider credentials encrypted in the DB."""
    import json

    encrypted = encrypt_field(json.dumps(config))
    settings_obj.sms_provider_config = {"encrypted": encrypted}
    await db.commit()
    await db.refresh(settings_obj)
    return settings_obj


def get_sms_provider_config(
    settings_obj: NotificationCompanySettings,
) -> dict[str, Any] | None:
    """Decrypt SMS provider config from DB."""
    import json

    if not settings_obj.sms_provider_config:
        return None
    encrypted = settings_obj.sms_provider_config.get("encrypted")
    if not encrypted:
        return None
    config: dict[str, Any] = json.loads(decrypt_field(encrypted))
    return config

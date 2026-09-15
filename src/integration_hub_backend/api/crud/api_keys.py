"""CRUD operations for API keys."""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from integration_hub_backend.api.core.security import generate_api_key
from integration_hub_backend.api.models.api_key import (
    ApiKeyCreate,
    ApiKeyCreated,
    NotificationApiKey,
)


async def create_api_key(
    db: AsyncSession, company_id: uuid.UUID, data: ApiKeyCreate
) -> ApiKeyCreated:
    data.validate_scopes()
    plaintext, prefix, key_hash = generate_api_key()

    api_key = NotificationApiKey(
        company_id=company_id,
        name=data.name,
        key_hash=key_hash,
        key_prefix=prefix,
        scopes=data.scopes,
        expires_at=data.expires_at,
    )
    db.add(api_key)
    await db.commit()
    await db.refresh(api_key)

    return ApiKeyCreated(
        id=api_key.id,
        name=api_key.name,
        key=plaintext,
        key_prefix=prefix,
        scopes=api_key.scopes,
        expires_at=api_key.expires_at,
        created_at=api_key.created_at,
    )


async def list_api_keys(db: AsyncSession, company_id: uuid.UUID) -> list[NotificationApiKey]:
    result = await db.execute(
        select(NotificationApiKey)
        .where(NotificationApiKey.company_id == company_id)
        .order_by(NotificationApiKey.created_at.desc())
    )
    return list(result.scalars().all())


async def revoke_api_key(
    db: AsyncSession, key_id: uuid.UUID, company_id: uuid.UUID
) -> NotificationApiKey | None:
    result = await db.execute(
        select(NotificationApiKey).where(
            NotificationApiKey.id == key_id,
            NotificationApiKey.company_id == company_id,
        )
    )
    key = result.scalar_one_or_none()
    if key:
        key.is_active = False
        await db.commit()
        await db.refresh(key)
    return key

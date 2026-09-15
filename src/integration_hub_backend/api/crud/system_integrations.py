"""CRUD operations for global system integrations."""

import json
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from integration_hub_backend.api.core.security import decrypt_field, encrypt_field
from integration_hub_backend.api.models.system_integration import NotificationSystemIntegration


async def get_system_integration(
    db: AsyncSession, name: str
) -> NotificationSystemIntegration | None:
    """Fetch a system integration by name."""
    result = await db.execute(
        select(NotificationSystemIntegration).where(NotificationSystemIntegration.name == name)
    )
    return result.scalar_one_or_none()


async def list_system_integrations(db: AsyncSession) -> list[NotificationSystemIntegration]:
    """List all system integrations (admin only)."""
    result = await db.execute(select(NotificationSystemIntegration))
    return list(result.scalars().all())


async def update_system_integration(
    db: AsyncSession,
    name: str,
    is_enabled: bool | None = None,
    config: dict[str, Any] | None = None,
) -> NotificationSystemIntegration:
    """Create or update a system-wide integration setting."""
    integration = await get_system_integration(db, name)

    if not integration:
        # Create if not exists
        integration = NotificationSystemIntegration(
            name=name, is_enabled=is_enabled if is_enabled is not None else False
        )
        if config is not None:
            integration.encrypted_config = encrypt_field(json.dumps(config))
        else:
            integration.encrypted_config = encrypt_field("{}")
        db.add(integration)
    else:
        if is_enabled is not None:
            integration.is_enabled = is_enabled
        if config is not None:
            integration.encrypted_config = encrypt_field(json.dumps(config))

    await db.commit()
    await db.refresh(integration)
    return integration


def get_system_decrypted(integration: NotificationSystemIntegration) -> dict[str, Any]:
    """Decrypt the configuration JSON blob."""
    try:
        decrypted = decrypt_field(integration.encrypted_config)
        config: dict[str, Any] = json.loads(decrypted)
        return config
    except Exception:
        return {}

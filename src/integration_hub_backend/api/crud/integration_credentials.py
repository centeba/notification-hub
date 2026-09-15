"""CRUD for IntegrationCredential — secrets are encrypted at rest, never returned."""

import json
import uuid
from typing import Any

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from integration_hub_backend.api.core.security import decrypt_field, encrypt_field
from integration_hub_backend.api.models.integration_credential import IntegrationCredential

log = structlog.get_logger(__name__)


async def create_credential(
    db: AsyncSession,
    company_id: uuid.UUID,
    name: str,
    type_: str,
    secret_data: dict[str, Any],
    connector: str | None = None,
) -> IntegrationCredential:
    encrypted = encrypt_field(json.dumps(secret_data))
    cred = IntegrationCredential(
        company_id=company_id,
        name=name,
        type=type_,
        connector=connector,
        encrypted_data=encrypted,
    )
    db.add(cred)
    await db.commit()
    await db.refresh(cred)
    log.info(
        "credential_created",
        credential_id=str(cred.id),
        company_id=str(company_id),
        type=type_,
        connector=connector,
        name=name,
    )
    return cred


async def list_credentials(
    db: AsyncSession,
    company_id: uuid.UUID,
    connector: str | None = None,
) -> list[IntegrationCredential]:
    stmt = select(IntegrationCredential).where(IntegrationCredential.company_id == company_id)
    if connector is not None:
        stmt = stmt.where(IntegrationCredential.connector == connector)
    stmt = stmt.order_by(IntegrationCredential.created_at.desc())
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def get_credential(
    db: AsyncSession,
    credential_id: uuid.UUID,
    company_id: uuid.UUID,
) -> IntegrationCredential | None:
    result = await db.execute(
        select(IntegrationCredential).where(
            IntegrationCredential.id == credential_id,
            IntegrationCredential.company_id == company_id,
        )
    )
    return result.scalar_one_or_none()


async def delete_credential(
    db: AsyncSession,
    credential_id: uuid.UUID,
    company_id: uuid.UUID,
) -> bool:
    cred = await get_credential(db, credential_id, company_id)
    if cred is None:
        return False

    cred_name = cred.name
    cred_type = cred.type

    await db.delete(cred)
    await db.commit()

    log.info(
        "credential_deleted",
        credential_id=str(credential_id),
        company_id=str(company_id),
        name=cred_name,
        type=cred_type,
    )
    return True


def get_decrypted(credential: IntegrationCredential) -> dict[str, Any]:
    """Decrypt and return the secret data dict. Never expose via API."""
    secret: dict[str, Any] = json.loads(decrypt_field(credential.encrypted_data))
    return secret

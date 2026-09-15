"""Phase G — CRUD for ``platform_llm_api_keys``.

Platform-level LLM keys are billed when an agent has
``scope='platform'``. They sit alongside (not inside) the per-tenant
``llm_api_keys`` store and have no ``company_id`` — there's exactly
one row per provider that the platform admin owns.

Auth: ``PlatformAdminDep`` on every route. Non-platform-admins
shouldn't see, mint, or rotate platform credentials.

The table itself is created by alembic migration 014 with columns:
``id``, ``provider``, ``key_encrypted``, ``is_active``,
``created_at``, ``updated_at``. We use raw SQL via the session for
the same reason ``get_platform_api_key`` does — there's no ORM
class in the ai_agent.py shim today and adding one just for this
trio of endpoints would double the surface area for no benefit.
"""

import uuid
from datetime import datetime

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from smart_llm.api.llm_service import get_key_store
from sqlalchemy import text

from integration_hub_backend.api.api.deps import (
    PlatformAdminDep,
    SessionDep,
)

router = APIRouter(prefix="/platform-llm-keys", tags=["platform-llm-keys"])


class PlatformLLMKeyPublic(BaseModel):
    id: uuid.UUID
    provider: str
    is_active: bool
    created_at: datetime | None = None
    updated_at: datetime | None = None


class PlatformLLMKeyCreate(BaseModel):
    provider: str = Field(..., description="anthropic | openai | gemini")
    api_key: str = Field(..., min_length=1)


@router.get("/", response_model=list[PlatformLLMKeyPublic])
async def list_platform_keys(
    session: SessionDep,
    _admin: PlatformAdminDep,
) -> list[PlatformLLMKeyPublic]:
    """List every registered platform-level key.

    ``key_encrypted`` is intentionally not returned — the API only
    surfaces metadata. To rotate a key the admin deletes + recreates
    it via this same router."""
    rows = (
        await session.execute(
            text(
                "SELECT id, provider, is_active, created_at, updated_at "
                "FROM platform_llm_api_keys ORDER BY provider"
            )
        )
    ).all()
    return [
        PlatformLLMKeyPublic(
            id=r[0],
            provider=r[1],
            is_active=r[2],
            created_at=r[3],
            updated_at=r[4],
        )
        for r in rows
    ]


@router.post("/", response_model=PlatformLLMKeyPublic)
async def create_platform_key(
    body: PlatformLLMKeyCreate,
    session: SessionDep,
    _admin: PlatformAdminDep,
) -> PlatformLLMKeyPublic:
    """Insert (or replace) the platform key for ``body.provider``.

    There's a UNIQUE constraint on ``provider`` (migration 014), so
    re-POSTing for an existing provider would 409. To rotate, the UI
    DELETEs first then re-POSTs.
    """
    store = get_key_store()
    encrypted = store._encrypt(body.api_key)  # noqa: SLF001 — intentional reuse

    new_id = uuid.uuid4()
    try:
        await session.execute(
            text(
                "INSERT INTO platform_llm_api_keys "
                "(id, provider, key_encrypted, is_active) "
                "VALUES (:id, :p, :k, TRUE)"
            ),
            {"id": new_id, "p": body.provider, "k": encrypted},
        )
        await session.commit()
    except Exception as e:
        await session.rollback()
        # Likely the unique-provider constraint — surface as 409.
        if "platform_llm_api_keys_provider" in str(e):
            raise HTTPException(
                status_code=409,
                detail=(
                    f"Platform key for provider '{body.provider}' already "
                    "exists. Delete it first to rotate."
                ),
            ) from e
        raise

    row = (
        await session.execute(
            text(
                "SELECT id, provider, is_active, created_at, updated_at "
                "FROM platform_llm_api_keys WHERE id = :id"
            ),
            {"id": new_id},
        )
    ).first()
    # Just inserted with this id above, so the row is always present.
    assert row is not None
    return PlatformLLMKeyPublic(
        id=row[0],
        provider=row[1],
        is_active=row[2],
        created_at=row[3],
        updated_at=row[4],
    )


@router.delete("/{key_id}", status_code=204)
async def delete_platform_key(
    key_id: uuid.UUID,
    session: SessionDep,
    _admin: PlatformAdminDep,
) -> None:
    row = (
        await session.execute(
            text("SELECT id FROM platform_llm_api_keys WHERE id = :id"),
            {"id": key_id},
        )
    ).first()
    if row is None:
        raise HTTPException(status_code=404, detail="Platform key not found")
    await session.execute(
        text("DELETE FROM platform_llm_api_keys WHERE id = :id"),
        {"id": key_id},
    )
    await session.commit()
    return None

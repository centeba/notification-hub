"""API key management endpoints."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, HTTPException, status

from integration_hub_backend.api.api.deps import CompanyAdminDep, RedisDep, SessionDep
from integration_hub_backend.api.core.cache import _key_api_key, cache_delete
from integration_hub_backend.api.crud.api_keys import create_api_key, list_api_keys, revoke_api_key
from integration_hub_backend.api.models.api_key import (
    ApiKeyCreate,
    ApiKeyCreated,
    ApiKeyPublic,
    ApiKeysPublic,
)

router = APIRouter(prefix="/api-keys", tags=["api-keys"])


@router.get("", response_model=ApiKeysPublic)
async def list_keys(
    current_user: CompanyAdminDep,
    db: SessionDep,
) -> ApiKeysPublic:
    if current_user.company_id is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="No company")
    keys = await list_api_keys(db, current_user.company_id)
    return ApiKeysPublic(
        data=[ApiKeyPublic.model_validate(k) for k in keys],
        count=len(keys),
    )


@router.post(
    "",
    response_model=ApiKeyCreated,
    status_code=status.HTTP_201_CREATED,
    summary="Create API key (plaintext returned once only)",
)
async def create_key(
    body: ApiKeyCreate,
    current_user: CompanyAdminDep,
    db: SessionDep,
) -> ApiKeyCreated:
    if current_user.company_id is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="No company")
    return await create_api_key(db, current_user.company_id, body)


@router.delete("/{key_id}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_key(
    key_id: uuid.UUID,
    current_user: CompanyAdminDep,
    db: SessionDep,
    redis: RedisDep,
) -> None:
    if current_user.company_id is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="No company")
    key = await revoke_api_key(db, key_id, current_user.company_id)
    if not key:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="API key not found")
    # Invalidate cache
    await cache_delete(redis, _key_api_key(key.key_prefix))

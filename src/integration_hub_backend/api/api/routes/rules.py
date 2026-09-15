"""Notification rules CRUD endpoints."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, HTTPException, Query, status

from integration_hub_backend.api.api.deps import CompanyAdminDep, CurrentUser, RedisDep, SessionDep
from integration_hub_backend.api.core.cache import (
    _key_active_rules,
    cache_delete,
)
from integration_hub_backend.api.crud.rules import (
    create_rule,
    delete_rule,
    get_rule,
    list_rules,
    update_rule,
)
from integration_hub_backend.api.models.rule import RuleCreate, RulePublic, RulesPublic, RuleUpdate

router = APIRouter(prefix="/rules", tags=["rules"])


@router.get("", response_model=RulesPublic)
async def list_rules_endpoint(
    current_user: CurrentUser,
    db: SessionDep,
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    active_only: bool = Query(False),
) -> RulesPublic:
    if current_user.company_id is None and not current_user.is_platform_admin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="No company associated")

    company_id = current_user.company_id
    rules, count = await list_rules(db, company_id, skip=skip, limit=limit, active_only=active_only)
    return RulesPublic(data=[RulePublic.model_validate(r) for r in rules], count=count)


@router.post("", response_model=RulePublic, status_code=status.HTTP_201_CREATED)
async def create_rule_endpoint(
    body: RuleCreate,
    current_user: CompanyAdminDep,
    db: SessionDep,
    redis: RedisDep,
) -> RulePublic:
    if current_user.company_id is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="No company associated")

    rule = await create_rule(db, current_user.company_id, current_user.user_id, body)
    await cache_delete(redis, _key_active_rules(str(current_user.company_id)))
    return RulePublic.model_validate(rule)


@router.get("/{rule_id}", response_model=RulePublic)
async def get_rule_endpoint(
    rule_id: uuid.UUID,
    current_user: CurrentUser,
    db: SessionDep,
) -> RulePublic:
    if current_user.company_id is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="No company")
    rule = await get_rule(db, rule_id, current_user.company_id)
    if not rule:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Rule not found")
    return RulePublic.model_validate(rule)


@router.patch("/{rule_id}", response_model=RulePublic)
async def update_rule_endpoint(
    rule_id: uuid.UUID,
    body: RuleUpdate,
    current_user: CompanyAdminDep,
    db: SessionDep,
    redis: RedisDep,
) -> RulePublic:
    if current_user.company_id is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="No company")
    rule = await get_rule(db, rule_id, current_user.company_id)
    if not rule:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Rule not found")
    updated = await update_rule(db, rule, body)
    await cache_delete(redis, _key_active_rules(str(current_user.company_id)))
    return RulePublic.model_validate(updated)


@router.delete("/{rule_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_rule_endpoint(
    rule_id: uuid.UUID,
    current_user: CompanyAdminDep,
    db: SessionDep,
    redis: RedisDep,
) -> None:
    if current_user.company_id is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="No company")
    rule = await get_rule(db, rule_id, current_user.company_id)
    if not rule:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Rule not found")
    await delete_rule(db, rule)
    await cache_delete(redis, _key_active_rules(str(current_user.company_id)))

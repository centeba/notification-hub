"""Notification templates CRUD endpoints."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, HTTPException, Query, status

from integration_hub_backend.api.api.deps import CompanyAdminDep, CurrentUser, SessionDep
from integration_hub_backend.api.crud.templates import (
    create_template,
    delete_template,
    get_template,
    list_templates,
    update_template,
)
from integration_hub_backend.api.models.template import (
    TemplateCreate,
    TemplatePublic,
    TemplatesPublic,
    TemplateUpdate,
)

router = APIRouter(prefix="/templates", tags=["templates"])


@router.get("", response_model=TemplatesPublic)
async def list_templates_endpoint(
    current_user: CurrentUser,
    db: SessionDep,
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    channel_id: uuid.UUID | None = None,
    language: str | None = None,
) -> TemplatesPublic:
    templates, count = await list_templates(
        db,
        company_id=current_user.company_id if not current_user.is_platform_admin else None,
        skip=skip,
        limit=limit,
        channel_id=channel_id,
        language=language,
    )
    return TemplatesPublic(data=[TemplatePublic.model_validate(t) for t in templates], count=count)


@router.post("", response_model=TemplatePublic, status_code=status.HTTP_201_CREATED)
async def create_template_endpoint(
    body: TemplateCreate,
    current_user: CompanyAdminDep,
    db: SessionDep,
) -> TemplatePublic:
    # Platform admins can create platform-wide templates (company_id=None)
    company_id = None if current_user.is_platform_admin else current_user.company_id
    template = await create_template(db, company_id, body)
    return TemplatePublic.model_validate(template)


@router.get("/{template_id}", response_model=TemplatePublic)
async def get_template_endpoint(
    template_id: uuid.UUID,
    current_user: CurrentUser,
    db: SessionDep,
) -> TemplatePublic:
    template = await get_template(
        db,
        template_id,
        company_id=None if current_user.is_platform_admin else current_user.company_id,
    )
    if not template:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Template not found")
    return TemplatePublic.model_validate(template)


@router.patch("/{template_id}", response_model=TemplatePublic)
async def update_template_endpoint(
    template_id: uuid.UUID,
    body: TemplateUpdate,
    current_user: CompanyAdminDep,
    db: SessionDep,
) -> TemplatePublic:
    template = await get_template(
        db,
        template_id,
        company_id=None if current_user.is_platform_admin else current_user.company_id,
    )
    if not template:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Template not found")
    # Prevent modifying platform-wide templates unless platform admin
    if template.company_id is None and not current_user.is_platform_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Cannot modify platform template"
        )
    updated = await update_template(db, template, body)
    return TemplatePublic.model_validate(updated)


@router.delete("/{template_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_template_endpoint(
    template_id: uuid.UUID,
    current_user: CompanyAdminDep,
    db: SessionDep,
) -> None:
    template = await get_template(
        db,
        template_id,
        company_id=None if current_user.is_platform_admin else current_user.company_id,
    )
    if not template:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Template not found")
    if template.company_id is None and not current_user.is_platform_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Cannot delete platform template"
        )
    await delete_template(db, template)

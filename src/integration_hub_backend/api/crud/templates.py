"""CRUD operations for notification templates."""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from integration_hub_backend.api.models.template import (
    NotificationTemplate,
    TemplateCreate,
    TemplateUpdate,
)


async def create_template(
    db: AsyncSession,
    company_id: uuid.UUID | None,
    data: TemplateCreate,
) -> NotificationTemplate:
    template = NotificationTemplate(
        name=data.name,
        company_id=company_id,
        channel_id=data.channel_id,
        language=data.language,
        subject=data.subject,
        body_html=data.body_html,
        body_text=data.body_text,
        webhook_payload_template=data.webhook_payload_template,
        variables=data.variables,
    )
    db.add(template)
    await db.commit()
    await db.refresh(template)
    return template


async def get_template(
    db: AsyncSession, template_id: uuid.UUID, company_id: uuid.UUID | None = None
) -> NotificationTemplate | None:
    query = select(NotificationTemplate).where(NotificationTemplate.id == template_id)
    if company_id is not None:
        # Company-scoped: allow own company templates or platform-wide (company_id IS NULL)
        from sqlalchemy import or_

        query = query.where(
            or_(
                NotificationTemplate.company_id == company_id,
                NotificationTemplate.company_id.is_(None),
            )
        )
    result = await db.execute(query)
    return result.scalar_one_or_none()


async def get_template_for_language(
    db: AsyncSession,
    template_id: uuid.UUID,
    language: str,
) -> NotificationTemplate | None:
    """Get a template for a specific language, falling back to 'en'."""
    result = await db.execute(
        select(NotificationTemplate).where(
            NotificationTemplate.id == template_id,
            NotificationTemplate.language == language,
            NotificationTemplate.is_active == True,  # noqa: E712
        )
    )
    template = result.scalar_one_or_none()
    if template is None and language != "en":
        # Fallback to English
        result = await db.execute(
            select(NotificationTemplate).where(
                NotificationTemplate.id == template_id,
                NotificationTemplate.language == "en",
                NotificationTemplate.is_active == True,  # noqa: E712
            )
        )
        template = result.scalar_one_or_none()
    return template


async def list_templates(
    db: AsyncSession,
    company_id: uuid.UUID | None,
    skip: int = 0,
    limit: int = 50,
    channel_id: uuid.UUID | None = None,
    language: str | None = None,
) -> tuple[list[NotificationTemplate], int]:
    from sqlalchemy import func, or_

    base = select(NotificationTemplate)
    if company_id is not None:
        base = base.where(
            or_(
                NotificationTemplate.company_id == company_id,
                NotificationTemplate.company_id.is_(None),
            )
        )
    if channel_id:
        base = base.where(NotificationTemplate.channel_id == channel_id)
    if language:
        base = base.where(NotificationTemplate.language == language)

    count_result = await db.execute(select(func.count()).select_from(base.subquery()))
    count = count_result.scalar_one()

    result = await db.execute(base.order_by(NotificationTemplate.name).offset(skip).limit(limit))
    return list(result.scalars().all()), count


async def update_template(
    db: AsyncSession, template: NotificationTemplate, data: TemplateUpdate
) -> NotificationTemplate:
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(template, field, value)
    await db.commit()
    await db.refresh(template)
    return template


async def delete_template(db: AsyncSession, template: NotificationTemplate) -> None:
    await db.delete(template)
    await db.commit()

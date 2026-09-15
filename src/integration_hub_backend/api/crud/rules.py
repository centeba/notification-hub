"""CRUD operations for notification rules."""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from integration_hub_backend.api.models.rule import NotificationRule, RuleCreate, RuleUpdate


async def create_rule(
    db: AsyncSession,
    company_id: uuid.UUID,
    created_by: uuid.UUID,
    data: RuleCreate,
) -> NotificationRule:
    rule = NotificationRule(
        name=data.name,
        company_id=company_id,
        created_by=created_by,
        event_type_id=data.event_type_id,
        channel_ids=[str(c) for c in data.channel_ids],
        conditions=[c.model_dump() for c in data.conditions] if data.conditions else None,
        recipient_strategy=data.recipient_strategy,
        recipient_config=data.recipient_config,
        template_id=data.template_id,
        priority=data.priority,
    )
    db.add(rule)
    await db.commit()
    await db.refresh(rule)
    return rule


async def get_rule(
    db: AsyncSession, rule_id: uuid.UUID, company_id: uuid.UUID
) -> NotificationRule | None:
    result = await db.execute(
        select(NotificationRule).where(
            NotificationRule.id == rule_id,
            NotificationRule.company_id == company_id,
        )
    )
    return result.scalar_one_or_none()


async def list_rules(
    db: AsyncSession,
    # None is passed by platform admins (no company scope); the equality filter
    # then becomes ``company_id IS NULL``.
    company_id: uuid.UUID | None,
    skip: int = 0,
    limit: int = 50,
    active_only: bool = False,
) -> tuple[list[NotificationRule], int]:
    query = select(NotificationRule).where(NotificationRule.company_id == company_id)
    if active_only:
        query = query.where(NotificationRule.is_active == True)  # noqa: E712
    query = query.order_by(NotificationRule.priority, NotificationRule.created_at.desc())

    count_query = select(NotificationRule).where(NotificationRule.company_id == company_id)
    if active_only:
        count_query = count_query.where(NotificationRule.is_active == True)  # noqa: E712

    result = await db.execute(query.offset(skip).limit(limit))
    rules = list(result.scalars().all())

    from sqlalchemy import func

    count_result = await db.execute(select(func.count()).select_from(count_query.subquery()))
    count = count_result.scalar_one()
    return rules, count


async def get_active_rules_for_event(
    db: AsyncSession,
    company_id: uuid.UUID,
    event_type_id: uuid.UUID,
) -> list[NotificationRule]:
    result = await db.execute(
        select(NotificationRule)
        .where(
            NotificationRule.company_id == company_id,
            NotificationRule.event_type_id == event_type_id,
            NotificationRule.is_active == True,  # noqa: E712
        )
        .order_by(NotificationRule.priority)
    )
    return list(result.scalars().all())


async def update_rule(
    db: AsyncSession, rule: NotificationRule, data: RuleUpdate
) -> NotificationRule:
    update_data = data.model_dump(exclude_unset=True)
    if "channel_ids" in update_data and update_data["channel_ids"] is not None:
        update_data["channel_ids"] = [str(c) for c in update_data["channel_ids"]]
    if "conditions" in update_data and update_data["conditions"] is not None:
        update_data["conditions"] = [
            c.model_dump() if hasattr(c, "model_dump") else c for c in update_data["conditions"]
        ]
    for field, value in update_data.items():
        setattr(rule, field, value)
    await db.commit()
    await db.refresh(rule)
    return rule


async def delete_rule(db: AsyncSession, rule: NotificationRule) -> None:
    await db.delete(rule)
    await db.commit()

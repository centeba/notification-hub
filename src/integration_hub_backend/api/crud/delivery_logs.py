"""CRUD operations for delivery logs."""

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from integration_hub_backend.api.core.security import encrypt_field
from integration_hub_backend.api.models.delivery_log import DeliveryStatus, NotificationDeliveryLog


async def create_delivery_log(
    db: AsyncSession,
    rule_id: uuid.UUID | None,
    event_type: str,
    event_payload: dict[str, Any] | None,
    channel: str,
    recipient_user_id: uuid.UUID | None,
    recipient_contact: str | None,
) -> NotificationDeliveryLog:
    log = NotificationDeliveryLog(
        rule_id=rule_id,
        event_type=event_type,
        event_payload=event_payload,
        channel=channel,
        recipient_user_id=recipient_user_id,
        # Encrypt PII before storing
        recipient_contact=encrypt_field(recipient_contact) if recipient_contact else None,
        status=DeliveryStatus.PENDING,
    )
    db.add(log)
    await db.commit()
    await db.refresh(log)
    return log


async def update_delivery_status(
    db: AsyncSession,
    log_id: uuid.UUID,
    status: DeliveryStatus,
    provider_message_id: str | None = None,
    error_message: str | None = None,
) -> NotificationDeliveryLog | None:
    result = await db.execute(
        select(NotificationDeliveryLog).where(NotificationDeliveryLog.id == log_id)
    )
    log = result.scalar_one_or_none()
    if log:
        log.status = status
        if provider_message_id:
            log.provider_message_id = provider_message_id
        if error_message:
            log.error_message = error_message
        if status == DeliveryStatus.SENT:
            log.sent_at = datetime.now(UTC)
        log.attempt_count += 1
        await db.commit()
        await db.refresh(log)
    return log


async def list_delivery_logs(
    db: AsyncSession,
    # None is passed by platform admins (no company scope); the equality filter
    # then becomes ``company_id IS NULL``.
    company_id: uuid.UUID | None,
    skip: int = 0,
    limit: int = 50,
    event_type: str | None = None,
    channel: str | None = None,
    status: DeliveryStatus | None = None,
    recipient_user_id: uuid.UUID | None = None,
) -> tuple[list[NotificationDeliveryLog], int]:
    from sqlalchemy import func, or_

    from integration_hub_backend.api.models.rule import NotificationRule

    # Tenant scoping comes from one of two places: a joined notification_rule
    # (the original rule-triggered path) OR the log row's own company_id
    # (rule-less platform alerts like AI budget_exhausted — Phase F).
    base = (
        select(NotificationDeliveryLog)
        .join(
            NotificationRule,
            NotificationDeliveryLog.rule_id == NotificationRule.id,
            isouter=True,
        )
        .where(
            or_(
                NotificationRule.company_id == company_id,
                NotificationDeliveryLog.company_id == company_id,
            )
        )
    )
    if event_type:
        base = base.where(NotificationDeliveryLog.event_type == event_type)
    if channel:
        base = base.where(NotificationDeliveryLog.channel == channel)
    if status:
        base = base.where(NotificationDeliveryLog.status == status)
    if recipient_user_id:
        base = base.where(NotificationDeliveryLog.recipient_user_id == recipient_user_id)

    count_result = await db.execute(select(func.count()).select_from(base.subquery()))
    count = count_result.scalar_one()

    result = await db.execute(
        base.order_by(NotificationDeliveryLog.created_at.desc()).offset(skip).limit(limit)
    )
    return list(result.scalars().all()), count

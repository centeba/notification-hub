"""NotificationDeliveryLog ORM model and Pydantic schemas."""

import uuid
from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel
from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from integration_hub_backend.api.core.db import Base


class DeliveryStatus(str, Enum):
    PENDING = "pending"
    SENT = "sent"
    FAILED = "failed"
    BOUNCED = "bounced"


class NotificationDeliveryLog(Base):
    __tablename__ = "notification_delivery_logs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    rule_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("notification_rules.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    # Tenant scope for rule-less platform alerts (e.g. AI budget exhausted).
    # Nullable for back-compat with rows that scope themselves via rule_id;
    # the list_delivery_logs query ORs the two together.
    company_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True, index=True
    )
    event_type: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    event_payload: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    channel: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    recipient_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True, index=True
    )
    # Encrypted at rest using AES-256-GCM
    recipient_contact: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default=DeliveryStatus.PENDING, index=True
    )
    provider_message_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    attempt_count: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


# ── Pydantic Schemas ──────────────────────────────────────────────────────────


class DeliveryLogPublic(BaseModel):
    id: uuid.UUID
    rule_id: uuid.UUID | None = None
    event_type: str
    channel: str
    recipient_user_id: uuid.UUID | None = None
    status: DeliveryStatus
    provider_message_id: str | None = None
    error_message: str | None = None
    attempt_count: int
    sent_at: datetime | None = None
    created_at: datetime
    # NOTE: recipient_contact (PII) is never exposed via public API

    model_config = {"from_attributes": True}


class DeliveryLogsPublic(BaseModel):
    data: list[DeliveryLogPublic]
    count: int

"""NotificationRule ORM model and Pydantic schemas."""

import uuid
from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, model_validator
from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from integration_hub_backend.api.core.db import Base


class RecipientStrategy(str, Enum):
    ALL_USERS = "all_users"
    ROLE = "role"
    SPECIFIC = "specific"
    EVENT_FIELD = "event_field"


class NotificationRule(Base):
    __tablename__ = "notification_rules"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    company_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    created_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    event_type_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("notification_event_types.id"),
        nullable=False,
        index=True,
    )
    channel_ids: Mapped[list[uuid.UUID]] = mapped_column(JSONB, nullable=False, default=list)
    # Stored as a JSON list of condition objects (see RuleCreate.conditions and
    # rules_engine.evaluate_conditions, which iterate it).
    conditions: Mapped[list[dict[str, Any]] | None] = mapped_column(JSONB, nullable=True)
    recipient_strategy: Mapped[str] = mapped_column(
        String(30), nullable=False, default=RecipientStrategy.ALL_USERS
    )
    recipient_config: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    template_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("notification_templates.id"),
        nullable=False,
    )
    priority: Mapped[int] = mapped_column(Integer, default=5, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


# ── Pydantic Schemas ──────────────────────────────────────────────────────────


class RuleCondition(BaseModel):
    """Simple condition evaluator: field op value."""

    field: str
    operator: str  # eq | ne | gt | gte | lt | lte | contains | in
    value: Any


class RuleCreate(BaseModel):
    name: str
    event_type_id: uuid.UUID
    channel_ids: list[uuid.UUID]
    conditions: list[RuleCondition] | None = None
    recipient_strategy: RecipientStrategy = RecipientStrategy.ALL_USERS
    recipient_config: dict[str, Any] | None = None
    template_id: uuid.UUID
    priority: int = 5

    @model_validator(mode="after")
    def validate_recipient_config(self) -> "RuleCreate":
        if self.recipient_strategy == RecipientStrategy.ROLE:
            if not self.recipient_config or "role" not in self.recipient_config:
                raise ValueError("recipient_config must contain 'role' for ROLE strategy")
        elif self.recipient_strategy == RecipientStrategy.SPECIFIC:
            if not self.recipient_config or "user_ids" not in self.recipient_config:
                raise ValueError("recipient_config must contain 'user_ids' for SPECIFIC strategy")
        elif self.recipient_strategy == RecipientStrategy.EVENT_FIELD:
            if not self.recipient_config or "field" not in self.recipient_config:
                raise ValueError("recipient_config must contain 'field' for EVENT_FIELD strategy")
        return self


class RuleUpdate(BaseModel):
    name: str | None = None
    channel_ids: list[uuid.UUID] | None = None
    conditions: list[RuleCondition] | None = None
    recipient_strategy: RecipientStrategy | None = None
    recipient_config: dict[str, Any] | None = None
    template_id: uuid.UUID | None = None
    priority: int | None = None
    is_active: bool | None = None


class RulePublic(BaseModel):
    id: uuid.UUID
    name: str
    company_id: uuid.UUID
    created_by: uuid.UUID
    event_type_id: uuid.UUID
    channel_ids: list[uuid.UUID]
    conditions: list[RuleCondition] | None = None
    recipient_strategy: RecipientStrategy
    recipient_config: dict[str, Any] | None = None
    template_id: uuid.UUID
    priority: int
    is_active: bool
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class RulesPublic(BaseModel):
    data: list[RulePublic]
    count: int

"""NotificationEventType ORM model and Pydantic schemas."""

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, field_validator
from sqlalchemy import Boolean, DateTime, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from integration_hub_backend.api.core.db import Base


class NotificationEventType(Base):
    __tablename__ = "notification_event_types"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(100), unique=True, nullable=False, index=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    entity_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    payload_schema: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    company_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True, index=True
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


# ── Pydantic Schemas ──────────────────────────────────────────────────────────


class EventTypeCreate(BaseModel):
    name: str
    description: str | None = None
    entity_type: str | None = None
    payload_schema: dict[str, Any] | None = None
    company_id: uuid.UUID | None = None

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str) -> str:
        v = v.strip().lower()
        if not v.replace(".", "_").replace("-", "_").replace("_", "").isalnum():
            raise ValueError("Event type name may only contain alphanumerics, dots, hyphens")
        return v


class EventTypeUpdate(BaseModel):
    description: str | None = None
    entity_type: str | None = None
    payload_schema: dict[str, Any] | None = None
    is_active: bool | None = None


class EventTypePublic(BaseModel):
    id: uuid.UUID
    name: str
    description: str | None = None
    entity_type: str | None = None
    payload_schema: dict[str, Any] | None = None
    company_id: uuid.UUID | None = None
    is_active: bool
    created_at: datetime

    model_config = {"from_attributes": True}


class EventTypesPublic(BaseModel):
    data: list[EventTypePublic]
    count: int

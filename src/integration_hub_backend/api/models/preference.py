"""NotificationPreference ORM model and Pydantic schemas."""

from __future__ import annotations

import uuid
from datetime import datetime, time

from pydantic import BaseModel
from sqlalchemy import Boolean, DateTime, ForeignKey, String, Time, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from integration_hub_backend.api.core.db import Base


class NotificationPreference(Base):
    __tablename__ = "notification_preferences"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True, index=True)
    company_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    channel_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("notification_channels.id"),
        nullable=False,
    )
    is_enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    language: Mapped[str | None] = mapped_column(String(10), nullable=True)
    quiet_hours_start: Mapped[time | None] = mapped_column(Time, nullable=True)
    quiet_hours_end: Mapped[time | None] = mapped_column(Time, nullable=True)
    timezone: Mapped[str] = mapped_column(String(50), default="UTC", nullable=False)
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


class PreferenceUpsert(BaseModel):
    channel_id: uuid.UUID
    is_enabled: bool = True
    language: str | None = None
    quiet_hours_start: time | None = None
    quiet_hours_end: time | None = None
    timezone: str = "UTC"


class PreferencePublic(BaseModel):
    id: uuid.UUID
    user_id: uuid.UUID | None = None
    company_id: uuid.UUID
    channel_id: uuid.UUID
    is_enabled: bool
    language: str | None = None
    quiet_hours_start: time | None = None
    quiet_hours_end: time | None = None
    timezone: str
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class PreferencesPublic(BaseModel):
    data: list[PreferencePublic]

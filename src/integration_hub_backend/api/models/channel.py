"""NotificationChannel ORM model and Pydantic schemas."""

import uuid
from typing import Any

from pydantic import BaseModel
from sqlalchemy import Boolean, String
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from integration_hub_backend.api.core.db import Base


class NotificationChannel(Base):
    __tablename__ = "notification_channels"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    config_schema: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)


# ── Pydantic Schemas ──────────────────────────────────────────────────────────


class ChannelPublic(BaseModel):
    id: uuid.UUID
    name: str
    is_active: bool
    config_schema: dict[str, Any] | None = None

    model_config = {"from_attributes": True}


class ChannelsPublic(BaseModel):
    data: list[ChannelPublic]
    count: int

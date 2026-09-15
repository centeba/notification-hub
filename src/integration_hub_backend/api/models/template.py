"""NotificationTemplate ORM model and Pydantic schemas."""

import uuid
from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel
from sqlalchemy import Boolean, DateTime, ForeignKey, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from integration_hub_backend.api.core.db import Base


class Language(str, Enum):
    EN = "en"
    ES = "es"
    FR = "fr"


SUPPORTED_LANGUAGES = [lang.value for lang in Language]
DEFAULT_LANGUAGE = Language.EN


class NotificationTemplate(Base):
    __tablename__ = "notification_templates"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    company_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True, index=True
    )
    channel_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("notification_channels.id"),
        nullable=False,
        index=True,
    )
    language: Mapped[str] = mapped_column(String(10), nullable=False, default="en")
    subject: Mapped[str | None] = mapped_column(Text, nullable=True)
    body_html: Mapped[str | None] = mapped_column(Text, nullable=True)
    body_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    webhook_payload_template: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    variables: Mapped[list[str] | None] = mapped_column(JSONB, nullable=True)
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


class TemplateCreate(BaseModel):
    name: str
    channel_id: uuid.UUID
    language: Language = Language.EN
    subject: str | None = None
    body_html: str | None = None
    body_text: str | None = None
    webhook_payload_template: dict[str, Any] | None = None
    variables: list[str] | None = None


class TemplateUpdate(BaseModel):
    name: str | None = None
    subject: str | None = None
    body_html: str | None = None
    body_text: str | None = None
    webhook_payload_template: dict[str, Any] | None = None
    variables: list[str] | None = None
    is_active: bool | None = None


class TemplatePublic(BaseModel):
    id: uuid.UUID
    name: str
    company_id: uuid.UUID | None = None
    channel_id: uuid.UUID
    language: str
    subject: str | None = None
    body_html: str | None = None
    body_text: str | None = None
    webhook_payload_template: dict[str, Any] | None = None
    variables: list[str] | None = None
    is_active: bool
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class TemplatesPublic(BaseModel):
    data: list[TemplatePublic]
    count: int

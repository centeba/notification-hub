"""NotificationSystemIntegration model for global observability settings."""

from __future__ import annotations

import uuid
from typing import Any

from pydantic import BaseModel
from sqlalchemy import Boolean, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from integration_hub_backend.api.core.db import Base


class NotificationSystemIntegration(Base):
    __tablename__ = "notification_system_integrations"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    # The provider name (e.g., 'datadog', 'splunk')
    name: Mapped[str] = mapped_column(String(50), unique=True, nullable=False, index=True)
    is_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    # AES-256-GCM encrypted JSON string containing API keys/URLs
    encrypted_config: Mapped[str] = mapped_column(Text, nullable=False)


# ── Pydantic Schemas ──────────────────────────────────────────────────────────


class SystemIntegrationUpdate(BaseModel):
    is_enabled: bool | None = None
    # Plan-text config passed for update, encrypted before storage
    config: dict[str, Any] | None = None


class SystemIntegrationPublic(BaseModel):
    id: uuid.UUID
    name: str
    is_enabled: bool
    # config is never returned in public schema for security

    model_config = {"from_attributes": True}

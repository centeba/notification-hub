"""NotificationWebhookEndpoint ORM model and Pydantic schemas."""

import uuid
from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, field_validator
from sqlalchemy import Boolean, DateTime, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from integration_hub_backend.api.core.db import Base


class WebhookAuthType(str, Enum):
    NONE = "none"
    BEARER = "bearer"
    BASIC = "basic"
    HMAC = "hmac"


class NotificationWebhookEndpoint(Base):
    __tablename__ = "notification_webhook_endpoints"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    url: Mapped[str] = mapped_column(Text, nullable=False)
    http_method: Mapped[str] = mapped_column(String(10), default="POST", nullable=False)
    # Encrypted custom headers JSON
    headers: Mapped[dict[str, str] | None] = mapped_column(JSONB, nullable=True)
    auth_type: Mapped[str] = mapped_column(String(20), default="none", nullable=False)
    # Encrypted auth credentials
    auth_config: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    timeout_seconds: Mapped[int] = mapped_column(Integer, default=30, nullable=False)
    retry_count: Mapped[int] = mapped_column(Integer, default=3, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


# ── Pydantic Schemas ──────────────────────────────────────────────────────────


class WebhookEndpointCreate(BaseModel):
    name: str
    url: str
    http_method: str = "POST"
    headers: dict[str, str] | None = None
    auth_type: WebhookAuthType = WebhookAuthType.NONE
    auth_config: dict[str, Any] | None = None
    timeout_seconds: int = 30
    retry_count: int = 3

    @field_validator("http_method")
    @classmethod
    def validate_method(cls, v: str) -> str:
        allowed = {"GET", "POST", "PUT", "PATCH", "DELETE"}
        v = v.upper()
        if v not in allowed:
            raise ValueError(f"http_method must be one of {allowed}")
        return v

    @field_validator("timeout_seconds")
    @classmethod
    def validate_timeout(cls, v: int) -> int:
        if not 1 <= v <= 300:
            raise ValueError("timeout_seconds must be between 1 and 300")
        return v

    @field_validator("retry_count")
    @classmethod
    def validate_retry(cls, v: int) -> int:
        if not 0 <= v <= 10:
            raise ValueError("retry_count must be between 0 and 10")
        return v


class WebhookEndpointUpdate(BaseModel):
    name: str | None = None
    url: str | None = None
    http_method: str | None = None
    headers: dict[str, str] | None = None
    auth_type: WebhookAuthType | None = None
    auth_config: dict[str, Any] | None = None
    timeout_seconds: int | None = None
    retry_count: int | None = None
    is_active: bool | None = None


class WebhookEndpointPublic(BaseModel):
    id: uuid.UUID
    company_id: uuid.UUID
    name: str
    url: str
    http_method: str
    auth_type: WebhookAuthType
    timeout_seconds: int
    retry_count: int
    is_active: bool
    created_at: datetime
    # NOTE: headers and auth_config (sensitive) are never returned

    model_config = {"from_attributes": True}


class WebhookEndpointsPublic(BaseModel):
    data: list[WebhookEndpointPublic]
    count: int

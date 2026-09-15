"""NotificationApiKey ORM model and Pydantic schemas."""

import uuid
from datetime import datetime

from pydantic import BaseModel
from sqlalchemy import Boolean, DateTime, String, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from integration_hub_backend.api.core.db import Base

VALID_SCOPES = frozenset(
    [
        # Notification scopes
        "notify:send",
        "rules:read",
        "rules:write",
        "templates:read",
        "templates:write",
        "logs:read",
        "preferences:read",
        "preferences:write",
        # Credential management
        "credentials:read",
        "credentials:write",
        # Integration execution
        "integrations:gmail",
        "integrations:outlook",
        "integrations:stripe",
        "integrations:s3",
        "integrations:google_drive",
        "integrations:mailchimp",
        "integrations:claude",
        "integrations:excel",
    ]
)


class NotificationApiKey(Base):
    __tablename__ = "notification_api_keys"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    key_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    key_prefix: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    scopes: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


# ── Pydantic Schemas ──────────────────────────────────────────────────────────


class ApiKeyCreate(BaseModel):
    name: str
    scopes: list[str] = ["notify:send"]
    expires_at: datetime | None = None

    def validate_scopes(self) -> None:
        invalid = set(self.scopes) - VALID_SCOPES
        if invalid:
            raise ValueError(f"Invalid scopes: {invalid}. Valid: {VALID_SCOPES}")


class ApiKeyCreated(BaseModel):
    """Returned ONCE on creation — plaintext key never stored."""

    id: uuid.UUID
    name: str
    key: str  # plaintext — shown once only
    key_prefix: str
    scopes: list[str]
    expires_at: datetime | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


class ApiKeyPublic(BaseModel):
    """Safe representation — no plaintext key."""

    id: uuid.UUID
    name: str
    key_prefix: str
    scopes: list[str]
    expires_at: datetime | None = None
    last_used_at: datetime | None = None
    is_active: bool
    created_at: datetime

    model_config = {"from_attributes": True}


class ApiKeysPublic(BaseModel):
    data: list[ApiKeyPublic]
    count: int

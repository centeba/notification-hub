"""IntegrationCredential ORM model and Pydantic schemas."""

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel
from sqlalchemy import DateTime, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from integration_hub_backend.api.core.db import Base


class IntegrationCredential(Base):
    __tablename__ = "integration_credentials"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    # api_key | oauth2 | basic_auth | aws
    type: Mapped[str] = mapped_column(String(50), nullable=False)
    # Catalog connector key (e.g. "stripe", "gmail") so a stored credential
    # maps back to a specific connector for the UI's "Connected" badge.
    # NULL for legacy/M2M rows that predate the chassis connect surface.
    connector: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    # AES-256-GCM encrypted JSON blob — never returned via API
    encrypted_data: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


# ── Pydantic Schemas ──────────────────────────────────────────────────────────

VALID_CREDENTIAL_TYPES = frozenset(
    [
        "api_key",
        "oauth2",
        "basic_auth",
        "aws",
        "datadog",
        "splunk",
        "grafana",
        "elasticsearch",
        "kibana",
    ]
)


class CredentialCreate(BaseModel):
    name: str
    type: str
    # Secret data — accepted on create, never returned
    secret_data: dict[str, Any]


class CredentialPublic(BaseModel):
    """Safe representation — no secrets."""

    id: uuid.UUID
    name: str
    type: str
    connector: str | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


class CredentialsPublic(BaseModel):
    data: list[CredentialPublic]
    count: int

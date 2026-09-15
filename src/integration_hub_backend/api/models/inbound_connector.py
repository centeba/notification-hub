"""InboundConnector — DB-backed inbound-claim connector registry (A4).

Replaces the in-code CONNECTORS dict so carrier/TPA feeds are per-company
runtime config: a row maps a vendor FNOL → a canonical event + a downstream
vertical endpoint (e.g. restoration's /intake/{key}). NULL company_id = a
global/shared connector.
"""

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel
from sqlalchemy import Boolean, DateTime, String, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from integration_hub_backend.api.core.db import Base


class InboundConnector(Base):
    __tablename__ = "inbound_connectors"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    key: Mapped[str] = mapped_column(String(80), unique=True, nullable=False, index=True)
    label: Mapped[str] = mapped_column(String(160), nullable=False)
    company_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True, index=True
    )
    event_type: Mapped[str] = mapped_column(String(100), nullable=False, default="claim.assigned")
    forward_url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    field_map: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default="{}"
    )
    # JSON Schema for the inbound vendor payload — enforced at ingest (A4 gap).
    # NULL = no validation (accept any payload).
    payload_schema: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class InboundConnectorCreate(BaseModel):
    key: str
    label: str
    company_id: uuid.UUID | None = None
    event_type: str = "claim.assigned"
    forward_url: str | None = None
    field_map: dict[str, Any] = {}
    payload_schema: dict[str, Any] | None = None
    is_active: bool = True


class InboundConnectorPublic(BaseModel):
    id: uuid.UUID
    key: str
    label: str
    company_id: uuid.UUID | None = None
    event_type: str
    forward_url: str | None = None
    field_map: dict[str, Any] = {}
    payload_schema: dict[str, Any] | None = None
    is_active: bool

    model_config = {"from_attributes": True}

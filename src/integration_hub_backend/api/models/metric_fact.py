"""MetricFact — generic cross-entity metrics/scorecard primitive (claims-platform A6).

FRAMEWORK primitive: a company-scoped fact = (metric_name, dimensions, value,
occurred_at). It carries NO domain knowledge — verticals decide what to record
(metric_name + dimension_keys + value), either by POSTing facts explicitly or by
the generic per-event auto-recorder (one count fact per ingested event_type).
Aggregation queries (sum / count / time-series) power dashboards + later feed
INS/TPA routing weighting.
"""

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel
from sqlalchemy import DateTime, Float, String, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from integration_hub_backend.api.core.db import Base


class MetricFact(Base):
    __tablename__ = "metric_facts"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    # e.g. "restoration.projects_created", "restoration.sla_breaches",
    # or an auto-recorded raw event_type like "claim.assigned".
    metric_name: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    # Flexible pivot dims, e.g. {"sla_category": "time_to_contact", "carrier": "acme"}.
    dimension_keys: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default="{}"
    )
    value: Mapped[float] = mapped_column(Float, nullable=False, default=1.0)
    # Provenance.
    event_type: Mapped[str | None] = mapped_column(String(120), nullable=True, index=True)
    event_id: Mapped[str | None] = mapped_column(String(100), nullable=True, index=True)
    # When the domain event occurred (drives aggregation); recorded_at = ingest time.
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True, server_default=func.now()
    )
    recorded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class MetricFactIn(BaseModel):
    """Explicit fact ingestion (verticals record domain metrics)."""

    metric_name: str
    value: float = 1.0
    dimension_keys: dict[str, Any] = {}
    event_type: str | None = None
    event_id: str | None = None
    occurred_at: datetime | None = None


class MetricFactPublic(BaseModel):
    id: uuid.UUID
    company_id: uuid.UUID
    metric_name: str
    dimension_keys: dict[str, Any] = {}
    value: float
    event_type: str | None = None
    occurred_at: datetime
    recorded_at: datetime

    model_config = {"from_attributes": True}

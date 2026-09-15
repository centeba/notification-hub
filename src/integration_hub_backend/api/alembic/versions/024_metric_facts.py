"""metric_facts — generic scorecard/analytics fact table (claims-platform A6)

Revision ID: 024_metric_facts
Revises: 023_connector_payload_schema
Create Date: 2026-06-29

Company-scoped fact store: (metric_name, dimension_keys, value, occurred_at).
Framework primitive — verticals decide what to record. Indexed for the common
aggregation paths (by company+metric, by time).
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision = "024_metric_facts"
down_revision = "023_connector_payload_schema"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "metric_facts",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("company_id", UUID(as_uuid=True), nullable=False),
        sa.Column("metric_name", sa.String(120), nullable=False),
        sa.Column("dimension_keys", JSONB, nullable=False, server_default="{}"),
        sa.Column("value", sa.Float(), nullable=False, server_default="1"),
        sa.Column("event_type", sa.String(120), nullable=True),
        sa.Column("event_id", sa.String(100), nullable=True),
        sa.Column(
            "occurred_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "recorded_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )
    op.create_index("ix_metric_facts_company_id", "metric_facts", ["company_id"])
    op.create_index("ix_metric_facts_metric_name", "metric_facts", ["metric_name"])
    op.create_index("ix_metric_facts_event_type", "metric_facts", ["event_type"])
    op.create_index("ix_metric_facts_event_id", "metric_facts", ["event_id"])
    op.create_index("ix_metric_facts_occurred_at", "metric_facts", ["occurred_at"])
    # Composite for the hot path: aggregate one metric for one company over time.
    op.create_index(
        "ix_metric_facts_company_metric_time",
        "metric_facts",
        ["company_id", "metric_name", "occurred_at"],
    )


def downgrade() -> None:
    op.drop_table("metric_facts")

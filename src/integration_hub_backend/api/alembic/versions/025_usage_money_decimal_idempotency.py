"""ai_usage_events — money as exact Decimal + idempotency key (readiness gate 9)

Revision ID: 025_usage_money_decimal_idempotency
Revises: 024_metric_facts
Create Date: 2026-08-03

The AI-spend ledger is summed to enforce the monthly budget cap, so it must be
exact — convert ``usd_cost`` from float to ``Numeric(14,6)``. Existing float
values cast cleanly (PG ``ALTER ... TYPE numeric USING usd_cost::numeric``).

Also add a nullable, unique ``idempotency_key`` so a retried provider call can't
double-count spend: the second insert with the same key is rejected and the
recorder returns the already-recorded cost. NULLs are allowed and don't collide
(SQL treats NULLs as distinct), so pre-existing rows and callers that don't
supply a key are unaffected.
"""

import sqlalchemy as sa
from alembic import op

revision = "025_usage_money_decimal_idempotency"
down_revision = "024_metric_facts"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column(
        "ai_usage_events",
        "usd_cost",
        type_=sa.Numeric(14, 6),
        existing_type=sa.Float(),
        existing_nullable=False,
        existing_server_default="0",
        postgresql_using="usd_cost::numeric(14,6)",
    )
    op.add_column(
        "ai_usage_events",
        sa.Column("idempotency_key", sa.String(120), nullable=True),
    )
    op.create_unique_constraint(
        "uq_ai_usage_events_idempotency_key",
        "ai_usage_events",
        ["idempotency_key"],
    )


def downgrade() -> None:
    op.drop_constraint("uq_ai_usage_events_idempotency_key", "ai_usage_events", type_="unique")
    op.drop_column("ai_usage_events", "idempotency_key")
    op.alter_column(
        "ai_usage_events",
        "usd_cost",
        type_=sa.Float(),
        existing_type=sa.Numeric(14, 6),
        existing_nullable=False,
        existing_server_default="0",
        postgresql_using="usd_cost::double precision",
    )

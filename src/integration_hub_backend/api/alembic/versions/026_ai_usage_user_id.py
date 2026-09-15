"""ai_usage_events — add user_id for per-user billing attribution

Revision ID: 026_ai_usage_user_id
Revises: 025_usage_money_decimal_idempotency
Create Date: 2026-08-05

Platform AI metering is centralized here; the usage row already carries
company_id + agent_id + skill_id. Add the individual ``user_id`` whose action
drove the spend so the platform billing view can break usage down per user.
Nullable (system/cron-triggered runs and legacy rows have no user) and indexed
for the group-by.
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "026_ai_usage_user_id"
down_revision = "025_usage_money_decimal_idempotency"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "ai_usage_events",
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_index("ix_ai_usage_events_user_id", "ai_usage_events", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_ai_usage_events_user_id", table_name="ai_usage_events")
    op.drop_column("ai_usage_events", "user_id")

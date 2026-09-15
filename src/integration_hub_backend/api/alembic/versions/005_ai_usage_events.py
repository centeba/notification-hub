"""Phase-E4 — ai_usage_events table + monthly_ai_budget_usd setting.

Backs :mod:`smart_llm.usage`. One row per provider call, summed
monthly per company; the budget check is a cheap aggregate against
``created_at`` (indexed). Adds ``monthly_ai_budget_usd`` to
``company_settings`` (0.0 = no cap).

Revision ID: 005_ai_usage_events
Revises: 004_seed_builtin_skills
Create Date: 2026-04-25
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "005_ai_usage_events"
down_revision = "004_seed_builtin_skills"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "ai_usage_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("company_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("agent_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("skill_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("provider", sa.String(40), nullable=False),
        sa.Column("model", sa.String(120), nullable=False),
        sa.Column("input_tokens", sa.Integer, nullable=False, server_default="0"),
        sa.Column("output_tokens", sa.Integer, nullable=False, server_default="0"),
        sa.Column("usd_cost", sa.Float, nullable=False, server_default="0"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index("ix_ai_usage_events_company_id", "ai_usage_events", ["company_id"])
    op.create_index("ix_ai_usage_events_agent_id", "ai_usage_events", ["agent_id"])
    op.create_index("ix_ai_usage_events_created_at", "ai_usage_events", ["created_at"])

    # Add ``monthly_ai_budget_usd`` to ``company_settings`` only if the
    # table exists in this DB (some test installs run a subset of
    # services). Use IF NOT EXISTS-guard so re-running is safe.
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM information_schema.tables
                       WHERE table_name = 'company_settings') THEN
                IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                               WHERE table_name = 'company_settings'
                                 AND column_name = 'monthly_ai_budget_usd') THEN
                    ALTER TABLE company_settings
                    ADD COLUMN monthly_ai_budget_usd DOUBLE PRECISION
                        NOT NULL DEFAULT 0.0;
                END IF;
            END IF;
        END $$;
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM information_schema.columns
                       WHERE table_name = 'company_settings'
                         AND column_name = 'monthly_ai_budget_usd') THEN
                ALTER TABLE company_settings DROP COLUMN monthly_ai_budget_usd;
            END IF;
        END $$;
        """
    )
    op.drop_index("ix_ai_usage_events_created_at", table_name="ai_usage_events")
    op.drop_index("ix_ai_usage_events_agent_id", table_name="ai_usage_events")
    op.drop_index("ix_ai_usage_events_company_id", table_name="ai_usage_events")
    op.drop_table("ai_usage_events")

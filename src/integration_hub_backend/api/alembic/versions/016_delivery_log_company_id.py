"""Add ``notification_delivery_logs.company_id``.

Existing delivery logs always belong to a ``notification_rules`` row,
and the list query at ``crud/delivery_logs.py:65`` joins through that
rule to filter by company. The AI-budget-exhausted alert (Phase F)
needs to land a row in this table with **no rule** attached (it's a
platform alert, not a triggered notification), so an explicit
``company_id`` column is required to keep tenant scoping intact.

Nullable to preserve compatibility with the existing rule-joined
rows; the list query is updated to OR over (rule.company_id, log.company_id).

Revision ID: 016_delivery_log_company_id
Revises: 015_company_monthly_ai_budget
Create Date: 2026-05-28
"""

from __future__ import annotations

from alembic import op

revision = "016_delivery_log_company_id"
down_revision = "015_company_monthly_ai_budget"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM information_schema.columns
                 WHERE table_name = 'notification_delivery_logs'
                   AND column_name = 'company_id'
            ) THEN
                ALTER TABLE notification_delivery_logs
                  ADD COLUMN company_id UUID NULL;
                CREATE INDEX IF NOT EXISTS ix_delivery_logs_company
                  ON notification_delivery_logs (company_id);
            END IF;
        END$$;
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DROP INDEX IF EXISTS ix_delivery_logs_company;
        ALTER TABLE notification_delivery_logs
          DROP COLUMN IF EXISTS company_id;
        """
    )

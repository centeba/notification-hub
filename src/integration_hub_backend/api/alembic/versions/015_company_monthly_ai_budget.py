"""Add ``notification_company_settings.monthly_ai_budget_usd``.

The AI Admin → Usage tab calls
``PATCH /api/v1/ai-usage/budget`` to set a per-company monthly cap.
That call dispatches to ``_set_company_budget`` in
``integration_hub_backend/api/api/main.py`` which does
``row.monthly_ai_budget_usd = value`` then commits. Before this
migration the column didn't exist; SQLAlchemy silently set a Python
attribute that doesn't map anywhere, the commit flushed only real
columns, and the next read fell through to the loader's
``getattr(row, "monthly_ai_budget_usd", 0.0)`` default. Symptom: the
UI showed Save success but the value never persisted.

Idempotent — uses information_schema like the surrounding Phase G
migrations so re-running against an already-upgraded DB is a no-op.

Revision ID: 015_company_monthly_ai_budget
Revises: 014_phase_g_grants_and_triggering
Create Date: 2026-05-24
"""

from __future__ import annotations

from alembic import op

revision = "015_company_monthly_ai_budget"
down_revision = "014_phase_g_grants_and_triggering"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM information_schema.columns
                 WHERE table_name = 'notification_company_settings'
                   AND column_name = 'monthly_ai_budget_usd'
            ) THEN
                ALTER TABLE notification_company_settings
                  ADD COLUMN monthly_ai_budget_usd DOUBLE PRECISION
                  NOT NULL DEFAULT 0.0;
            END IF;
        END$$;
        """
    )


def downgrade() -> None:
    op.execute(
        """
        ALTER TABLE notification_company_settings
          DROP COLUMN IF EXISTS monthly_ai_budget_usd;
        """
    )

"""Add ``integration_credentials.connector``.

The chassis Integration Hub "Integrations" tab lets a company admin
connect a connector (Stripe, Datadog, …) from the UI via a JWT-gated
``POST /credentials/connect``. To render a per-connector "Connected"
badge, a stored credential must map back to a specific catalog key —
but generic API-key connectors all share ``type='api_key'`` and are
otherwise indistinguishable. This column stores the catalog connector
key (e.g. "stripe", "gmail") so status can be computed as "a row exists
with this connector for my company".

Nullable to preserve compatibility with legacy/M2M rows that predate
the connect surface (they stay NULL and simply don't show a badge).

Revision ID: 017_integration_credentials_connector
Revises: 016_delivery_log_company_id
Create Date: 2026-06-01
"""

from __future__ import annotations

from alembic import op

revision = "017_integration_credentials_connector"
down_revision = "016_delivery_log_company_id"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM information_schema.columns
                 WHERE table_name = 'integration_credentials'
                   AND column_name = 'connector'
            ) THEN
                ALTER TABLE integration_credentials
                  ADD COLUMN connector VARCHAR(64) NULL;
                CREATE INDEX IF NOT EXISTS ix_integration_credentials_connector
                  ON integration_credentials (connector);
            END IF;
        END$$;
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DROP INDEX IF EXISTS ix_integration_credentials_connector;
        ALTER TABLE integration_credentials
          DROP COLUMN IF EXISTS connector;
        """
    )

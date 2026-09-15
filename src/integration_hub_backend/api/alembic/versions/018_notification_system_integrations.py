"""Create ``notification_system_integrations``.

The ``NotificationSystemIntegration`` ORM model and the admin observability
routes (plus the observability connector action routes' global-config
fallback) have always referenced this table, but **no migration ever
created it** — so any read of the global integration config 500'd with
``UndefinedTableError``. This adds the missing table.

It holds the platform-wide (global) observability connector config
(datadog/splunk/grafana/elasticsearch/kibana). Per-company connector
credentials live in ``integration_credentials`` (the Connect UI); the
resolver prefers those and falls back to this table.

Idempotent: only creates the table when absent.

Revision ID: 018_notification_system_integrations
Revises: 017_integration_credentials_connector
Create Date: 2026-06-01
"""

from __future__ import annotations

from alembic import op

revision = "018_notification_system_integrations"
down_revision = "017_integration_credentials_connector"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Single statement (DO block) — asyncpg rejects multiple commands in one
    # prepared statement, so the CREATE TABLE + CREATE INDEX are wrapped
    # together (matches the surrounding migrations' style).
    op.execute(
        """
        DO $$
        BEGIN
            CREATE TABLE IF NOT EXISTS notification_system_integrations (
                id UUID PRIMARY KEY,
                name VARCHAR(50) NOT NULL,
                is_enabled BOOLEAN NOT NULL DEFAULT FALSE,
                encrypted_config TEXT NOT NULL
            );
            CREATE UNIQUE INDEX IF NOT EXISTS ix_notification_system_integrations_name
              ON notification_system_integrations (name);
        END$$;
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DO $$
        BEGIN
            DROP INDEX IF EXISTS ix_notification_system_integrations_name;
            DROP TABLE IF EXISTS notification_system_integrations;
        END$$;
        """
    )

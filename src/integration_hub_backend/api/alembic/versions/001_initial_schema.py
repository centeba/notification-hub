"""Initial notification hub schema.

Revision ID: 001_initial
Revises:
Create Date: 2026-03-28
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "001_initial"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── notification_channels ─────────────────────────────────────────────────
    op.create_table(
        "notification_channels",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.String(50), nullable=False, unique=True),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default="true"),
        sa.Column("config_schema", postgresql.JSONB, nullable=True),
    )

    # Seed default channels
    op.execute(
        sa.text(
            """
            INSERT INTO notification_channels (id, name, is_active) VALUES
            (gen_random_uuid(), 'email', true),
            (gen_random_uuid(), 'sms', true),
            (gen_random_uuid(), 'webhook', true)
            """
        )
    )

    # ── notification_event_types ──────────────────────────────────────────────
    op.create_table(
        "notification_event_types",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.String(100), nullable=False, unique=True),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("entity_type", sa.String(50), nullable=True),
        sa.Column("payload_schema", postgresql.JSONB, nullable=True),
        sa.Column("company_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default="true"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("NOW()"),
            nullable=False,
        ),
    )
    op.create_index("ix_event_types_name", "notification_event_types", ["name"])
    op.create_index("ix_event_types_company", "notification_event_types", ["company_id"])

    # Seed common platform-wide event types
    op.execute(
        """
        INSERT INTO notification_event_types (id, name, description, entity_type, is_active) VALUES
        (gen_random_uuid(), 'user.registered', 'New user registered', 'user', true),
        (gen_random_uuid(), 'user.password_reset', 'User requested password reset', 'user', true),
        (gen_random_uuid(), 'user.login_failed', 'Failed login attempt', 'user', true),
        (gen_random_uuid(), 'order.created', 'New order created', 'order', true),
        (gen_random_uuid(), 'order.status_changed', 'Order status changed', 'order', true),
        (gen_random_uuid(), 'payment.received', 'Payment received', 'payment', true),
        (gen_random_uuid(), 'payment.failed', 'Payment failed', 'payment', true),
        (gen_random_uuid(), 'system.alert', 'System alert notification', 'system', true)
        """
    )

    # ── notification_company_settings ─────────────────────────────────────────
    op.create_table(
        "notification_company_settings",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("company_id", postgresql.UUID(as_uuid=True), nullable=False, unique=True),
        sa.Column("default_language", sa.String(10), nullable=False, server_default="'en'"),
        sa.Column("sms_provider", sa.String(20), nullable=False, server_default="'twilio'"),
        sa.Column("sms_provider_config", postgresql.JSONB, nullable=True),
        sa.Column("email_from_address", sa.String(255), nullable=True),
        sa.Column("email_from_name", sa.String(255), nullable=True),
        sa.Column("webhook_secret_key", sa.String(255), nullable=True),
        sa.Column("max_notifications_per_day", sa.Integer, nullable=False, server_default="10000"),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default="true"),
    )
    op.create_index("ix_company_settings_company", "notification_company_settings", ["company_id"])

    # ── notification_api_keys ─────────────────────────────────────────────────
    op.create_table(
        "notification_api_keys",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("company_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("key_hash", sa.String(255), nullable=False),
        sa.Column("key_prefix", sa.String(20), nullable=False),
        sa.Column("scopes", postgresql.JSONB, nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default="true"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("NOW()"),
            nullable=False,
        ),
    )
    op.create_index("ix_api_keys_company", "notification_api_keys", ["company_id"])
    op.create_index("ix_api_keys_prefix", "notification_api_keys", ["key_prefix"])

    # ── notification_webhook_endpoints ────────────────────────────────────────
    op.create_table(
        "notification_webhook_endpoints",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("company_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("url", sa.Text, nullable=False),
        sa.Column("http_method", sa.String(10), nullable=False, server_default="'POST'"),
        sa.Column("headers", postgresql.JSONB, nullable=True),
        sa.Column("auth_type", sa.String(20), nullable=False, server_default="'none'"),
        sa.Column("auth_config", postgresql.JSONB, nullable=True),
        sa.Column("timeout_seconds", sa.Integer, nullable=False, server_default="30"),
        sa.Column("retry_count", sa.Integer, nullable=False, server_default="3"),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default="true"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("NOW()"),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_webhook_endpoints_company", "notification_webhook_endpoints", ["company_id"]
    )

    # ── notification_templates ────────────────────────────────────────────────
    op.create_table(
        "notification_templates",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("company_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "channel_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("notification_channels.id"),
            nullable=False,
        ),
        sa.Column("language", sa.String(10), nullable=False, server_default="'en'"),
        sa.Column("subject", sa.Text, nullable=True),
        sa.Column("body_html", sa.Text, nullable=True),
        sa.Column("body_text", sa.Text, nullable=True),
        sa.Column("webhook_payload_template", postgresql.JSONB, nullable=True),
        sa.Column("variables", postgresql.JSONB, nullable=True),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default="true"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("NOW()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("NOW()"),
            nullable=False,
        ),
    )
    op.create_index("ix_templates_company", "notification_templates", ["company_id"])
    op.create_index("ix_templates_channel", "notification_templates", ["channel_id"])
    op.create_index("ix_templates_name", "notification_templates", ["name"])

    # ── notification_rules ────────────────────────────────────────────────────
    op.create_table(
        "notification_rules",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("company_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "event_type_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("notification_event_types.id"),
            nullable=False,
        ),
        sa.Column("channel_ids", postgresql.JSONB, nullable=False),
        sa.Column("conditions", postgresql.JSONB, nullable=True),
        sa.Column(
            "recipient_strategy", sa.String(30), nullable=False, server_default="'all_users'"
        ),
        sa.Column("recipient_config", postgresql.JSONB, nullable=True),
        sa.Column(
            "template_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("notification_templates.id"),
            nullable=False,
        ),
        sa.Column("priority", sa.Integer, nullable=False, server_default="5"),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default="true"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("NOW()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("NOW()"),
            nullable=False,
        ),
    )
    op.create_index("ix_rules_company", "notification_rules", ["company_id"])
    op.create_index("ix_rules_event_type", "notification_rules", ["event_type_id"])

    # ── notification_preferences ──────────────────────────────────────────────
    op.create_table(
        "notification_preferences",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("company_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "channel_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("notification_channels.id"),
            nullable=False,
        ),
        sa.Column("is_enabled", sa.Boolean, nullable=False, server_default="true"),
        sa.Column("language", sa.String(10), nullable=True),
        sa.Column("quiet_hours_start", sa.Time, nullable=True),
        sa.Column("quiet_hours_end", sa.Time, nullable=True),
        sa.Column("timezone", sa.String(50), nullable=False, server_default="'UTC'"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("NOW()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("NOW()"),
            nullable=False,
        ),
    )
    op.create_index("ix_preferences_user", "notification_preferences", ["user_id"])
    op.create_index("ix_preferences_company", "notification_preferences", ["company_id"])

    # ── notification_delivery_logs ────────────────────────────────────────────
    op.create_table(
        "notification_delivery_logs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "rule_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("notification_rules.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("event_type", sa.String(100), nullable=False),
        sa.Column("event_payload", postgresql.JSONB, nullable=True),
        sa.Column("channel", sa.String(50), nullable=False),
        sa.Column("recipient_user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("recipient_contact", sa.Text, nullable=True),  # AES-256-GCM encrypted
        sa.Column("status", sa.String(20), nullable=False, server_default="'pending'"),
        sa.Column("provider_message_id", sa.Text, nullable=True),
        sa.Column("error_message", sa.Text, nullable=True),
        sa.Column("attempt_count", sa.Integer, nullable=False, server_default="1"),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("NOW()"),
            nullable=False,
        ),
    )
    op.create_index("ix_delivery_logs_rule", "notification_delivery_logs", ["rule_id"])
    op.create_index("ix_delivery_logs_event_type", "notification_delivery_logs", ["event_type"])
    op.create_index("ix_delivery_logs_channel", "notification_delivery_logs", ["channel"])
    op.create_index(
        "ix_delivery_logs_recipient", "notification_delivery_logs", ["recipient_user_id"]
    )
    op.create_index("ix_delivery_logs_status", "notification_delivery_logs", ["status"])
    op.create_index("ix_delivery_logs_created", "notification_delivery_logs", ["created_at"])


def downgrade() -> None:
    op.drop_table("notification_delivery_logs")
    op.drop_table("notification_preferences")
    op.drop_table("notification_rules")
    op.drop_table("notification_templates")
    op.drop_table("notification_webhook_endpoints")
    op.drop_table("notification_api_keys")
    op.drop_table("notification_company_settings")
    op.drop_table("notification_event_types")
    op.drop_table("notification_channels")

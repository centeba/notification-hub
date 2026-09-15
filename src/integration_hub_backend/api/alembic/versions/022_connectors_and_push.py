"""inbound_connectors + device_tokens + push channel (A4 DB registry, A8 push)

Revision ID: 022_connectors_and_push
Revises: 021_ai_skill_agent_only
Create Date: 2026-06-29

DB-backed per-company inbound-connector registry (A4) + push device tokens and a
'push' notification channel (A8). Seeds the generic/acme_fnol connectors so the
gateway keeps working, and the push channel so rules can target it.
"""

import uuid

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision = "022_connectors_and_push"
down_revision = "021_ai_skill_agent_only"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "inbound_connectors",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("key", sa.String(80), nullable=False),
        sa.Column("label", sa.String(160), nullable=False),
        sa.Column("company_id", UUID(as_uuid=True), nullable=True),
        sa.Column("event_type", sa.String(100), nullable=False, server_default="claim.assigned"),
        sa.Column("forward_url", sa.String(512), nullable=True),
        sa.Column("field_map", JSONB, nullable=False, server_default="{}"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.UniqueConstraint("key", name="uq_inbound_connectors_key"),
    )
    op.create_index("ix_inbound_connectors_key", "inbound_connectors", ["key"])
    op.create_index("ix_inbound_connectors_company_id", "inbound_connectors", ["company_id"])

    op.create_table(
        "device_tokens",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", UUID(as_uuid=True), nullable=False),
        sa.Column("company_id", UUID(as_uuid=True), nullable=False),
        sa.Column("platform", sa.String(20), nullable=False),
        sa.Column("token", sa.String(512), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.UniqueConstraint("platform", "token", name="uq_device_tokens_platform_token"),
    )
    op.create_index("ix_device_tokens_user_id", "device_tokens", ["user_id"])
    op.create_index("ix_device_tokens_company_id", "device_tokens", ["company_id"])

    # Seed the default inbound connectors (mirror the prior in-code registry).
    conn = sa.table(
        "inbound_connectors",
        sa.column("id", UUID(as_uuid=True)),
        sa.column("key", sa.String),
        sa.column("label", sa.String),
        sa.column("company_id", UUID(as_uuid=True)),
        sa.column("event_type", sa.String),
        sa.column("forward_url", sa.String),
        sa.column("field_map", JSONB),
        sa.column("is_active", sa.Boolean),
    )
    base = "http://host.docker.internal:8010"
    op.bulk_insert(
        conn,
        [
            {
                "id": uuid.uuid4(),
                "key": "generic",
                "label": "Generic claim intake",
                "company_id": None,
                "event_type": "claim.assigned",
                "forward_url": f"{base}/intake/generic",
                "field_map": {},
                "is_active": True,
            },
            {
                "id": uuid.uuid4(),
                "key": "acme_fnol",
                "label": "ACME Carrier FNOL",
                "company_id": None,
                "event_type": "claim.assigned",
                "forward_url": f"{base}/intake/acme_fnol",
                "field_map": {},
                "is_active": True,
            },
        ],
    )

    # Seed the 'push' notification channel (idempotent — skip if present).
    op.execute(
        "INSERT INTO notification_channels (id, name, is_active) "
        f"VALUES ('{uuid.uuid4()}', 'push', true) "
        "ON CONFLICT (name) DO NOTHING"
    )


def downgrade() -> None:
    op.execute("DELETE FROM notification_channels WHERE name = 'push'")
    op.drop_table("device_tokens")
    op.drop_table("inbound_connectors")

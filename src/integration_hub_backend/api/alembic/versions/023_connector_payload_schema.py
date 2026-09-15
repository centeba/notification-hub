"""inbound_connectors.payload_schema — inbound payload validation (A4 gap)

Revision ID: 023_connector_payload_schema
Revises: 022_connectors_and_push
Create Date: 2026-06-29

Adds an optional JSON-Schema column so the ingest gateway can validate a vendor
FNOL payload before transform/publish. NULL = accept any payload (back-compat).
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "023_connector_payload_schema"
down_revision = "022_connectors_and_push"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "inbound_connectors",
        sa.Column("payload_schema", JSONB, nullable=True),
    )


def downgrade() -> None:
    op.drop_column("inbound_connectors", "payload_schema")

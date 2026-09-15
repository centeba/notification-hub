"""PII masking policy + egress audit columns (PII firewall PR2)

Adds the per-company PII masking policy that the smart-llm MaskingProvider
firewall reads, plus an audit column on the shared usage table.

``notification_company_settings``:
  * ``pii_masking_policy VARCHAR(20) NULL`` — 'off' | 'detect-only' | 'enforce'
    | 'strict'. NULL means the company hasn't set a value, so the effective
    policy falls back to ``SMART_LLM_PII_DEFAULT_POLICY`` (default 'enforce') —
    masking is on out-of-the-box; a company admin sets an explicit value to
    relax it.
  * ``pii_categories JSONB NULL`` — optional allowlist of PII types to mask
    (NULL = all).

``ai_usage_events``:
  * ``pii_masking JSONB NULL`` — counts-only masking summary attached per call
    (populated by a later PR; the column lands here so the schema is ready).

Revision ID: 028_pii_masking
Revises: 027_llm_api_keys
Create Date: 2026-08-22
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "028_pii_masking"
down_revision = "027_llm_api_keys"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "notification_company_settings",
        sa.Column("pii_masking_policy", sa.String(length=20), nullable=True),
    )
    op.add_column(
        "notification_company_settings",
        sa.Column("pii_categories", JSONB(), nullable=True),
    )
    op.add_column(
        "ai_usage_events",
        sa.Column("pii_masking", JSONB(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("ai_usage_events", "pii_masking")
    op.drop_column("notification_company_settings", "pii_categories")
    op.drop_column("notification_company_settings", "pii_masking_policy")

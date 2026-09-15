"""Add source_app column to ai_agent_configs.

Mirrors the column added to ai_skills in 011 — agents synced by vertical
apps (restoration, future wealth-mgmt, etc.) via the SDK's AgentBundle
carry a source_app value. The AI Admin UI renders rows with
source_app != NULL as read-only; PATCH/DELETE return 403. Editing happens
by changing the YAML in the vertical's repo and redeploying.

Revision ID: 012_ai_agent_configs_source_app
Revises: 011_ai_skills_source_app
Create Date: 2026-04-30
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "012_ai_agent_configs_source_app"
down_revision = "011_ai_skills_source_app"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "ai_agent_configs",
        sa.Column("source_app", sa.String(length=100), nullable=True),
    )
    op.create_index(
        "ix_ai_agent_configs_source_app",
        "ai_agent_configs",
        ["source_app"],
    )


def downgrade() -> None:
    op.drop_index("ix_ai_agent_configs_source_app", "ai_agent_configs")
    op.drop_column("ai_agent_configs", "source_app")

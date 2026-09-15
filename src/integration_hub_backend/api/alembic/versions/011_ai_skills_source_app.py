"""Add source_app column to ai_skills.

Skills synced by vertical apps (restoration, future wealth-mgmt, etc.) via
the SDK's SkillBundle.register_with() carry a `source_app` value. The AI
Admin UI renders rows with `source_app != NULL` as read-only; the API
returns 403 on PATCH/DELETE for those rows. Editing happens by changing
the YAML in the vertical's repo and redeploying.

Revision ID: 011_ai_skills_source_app
Revises: 010_attach_rule_skills
Create Date: 2026-04-30
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "011_ai_skills_source_app"
down_revision = "010_attach_rule_skills"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "ai_skills",
        sa.Column("source_app", sa.String(length=100), nullable=True),
    )
    # Indexed because the /sync endpoint looks up rows by (name, source_app)
    # plus we want efficient filtering in the UI ("show only skills from app X").
    op.create_index(
        "ix_ai_skills_source_app",
        "ai_skills",
        ["source_app"],
    )


def downgrade() -> None:
    op.drop_index("ix_ai_skills_source_app", "ai_skills")
    op.drop_column("ai_skills", "source_app")

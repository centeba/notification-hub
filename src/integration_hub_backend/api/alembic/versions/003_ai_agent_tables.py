"""Create ai_skills / ai_agent_configs / ai_agent_skill_links tables.

These back the smart-llm-owned ORM models built via
``smart_llm.db.make_ai_models(Base)``. The tables ship with the new
``kind`` (``prompt`` | ``python_tool``) and ``modality`` (``document`` |
``image`` | ``video`` | ``audio`` | ``text`` | ``any``) columns on
``ai_skills`` so the registry-aware workflow palette works out of the
box.

Revision ID: 003_ai_agent_tables
Revises: 002_integration_credentials
Create Date: 2026-04-25
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "003_ai_agent_tables"
down_revision = "002_integration_credentials"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── ai_skills ─────────────────────────────────────────────────────────────
    op.create_table(
        "ai_skills",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("company_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("label", sa.String(255), nullable=True),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("icon", sa.String(100), nullable=True),
        sa.Column(
            "kind",
            sa.String(32),
            nullable=False,
            server_default="prompt",
        ),
        sa.Column(
            "modality",
            sa.String(32),
            nullable=False,
            server_default="any",
        ),
        sa.Column("content", sa.Text, nullable=True),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default="true"),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=False),
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
    op.create_index("ix_ai_skills_company_id", "ai_skills", ["company_id"])
    op.create_index("ix_ai_skills_name", "ai_skills", ["name"])
    op.create_index("ix_ai_skills_kind", "ai_skills", ["kind"])
    op.create_index("ix_ai_skills_modality", "ai_skills", ["modality"])

    # ── ai_agent_configs ──────────────────────────────────────────────────────
    op.create_table(
        "ai_agent_configs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("company_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("label", sa.String(255), nullable=True),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("icon", sa.String(100), nullable=True),
        sa.Column("system_prompt", sa.Text, nullable=True),
        sa.Column(
            "provider_type",
            sa.String(50),
            nullable=False,
            server_default="anthropic",
        ),
        sa.Column(
            "model_name",
            sa.String(255),
            nullable=False,
            server_default="claude-3-5-sonnet-20240620",
        ),
        sa.Column("model_configuration", sa.Text, nullable=True),
        sa.Column("response_format", sa.String(50), nullable=True),
        sa.Column("role_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default="true"),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=False),
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
    op.create_index("ix_ai_agent_configs_company_id", "ai_agent_configs", ["company_id"])
    op.create_index("ix_ai_agent_configs_name", "ai_agent_configs", ["name"])

    # ── ai_agent_skill_links ──────────────────────────────────────────────────
    op.create_table(
        "ai_agent_skill_links",
        sa.Column(
            "agent_config_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("ai_agent_configs.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "skill_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("ai_skills.id", ondelete="CASCADE"),
            primary_key=True,
        ),
    )


def downgrade() -> None:
    op.drop_table("ai_agent_skill_links")
    op.drop_index("ix_ai_agent_configs_name", "ai_agent_configs")
    op.drop_index("ix_ai_agent_configs_company_id", "ai_agent_configs")
    op.drop_table("ai_agent_configs")
    op.drop_index("ix_ai_skills_modality", "ai_skills")
    op.drop_index("ix_ai_skills_kind", "ai_skills")
    op.drop_index("ix_ai_skills_name", "ai_skills")
    op.drop_index("ix_ai_skills_company_id", "ai_skills")
    op.drop_table("ai_skills")

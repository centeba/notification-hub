"""Add ``agent_only`` flag to ai_skills.

When true, a skill is only usable inside an agent's reasoning loop (as an
allow-listed tool) and is NOT offered as a directly-droppable node in the
workflow builder. ``kind='prompt'`` skills are implicitly agent-only (a prompt
fragment is never directly callable); this flag lets an author additionally
mark a ``python_tool`` skill agent-only when it relies on the agent's context.

Factory-defined columns aren't autogen-visible, so this is hand-written to
match ``AISkill.agent_only`` in ``smart_llm.db.models`` (mirrors 019/020).

Idempotent.

Revision ID: 021_ai_skill_agent_only
Revises: 020_ai_unique_company_name
Create Date: 2026-06-08
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "021_ai_skill_agent_only"
down_revision = "020_ai_unique_company_name"
branch_labels = None
depends_on = None


def _has_column(table: str, column: str) -> bool:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    return column in {c["name"] for c in insp.get_columns(table)}


def upgrade() -> None:
    if not _has_column("ai_skills", "agent_only"):
        op.add_column(
            "ai_skills",
            sa.Column(
                "agent_only",
                sa.Boolean(),
                nullable=False,
                server_default=sa.text("false"),
            ),
        )


def downgrade() -> None:
    if _has_column("ai_skills", "agent_only"):
        op.drop_column("ai_skills", "agent_only")

"""Seed the inactive Rule Builder agent for every existing company.

Backs the Phase-D refactor of ``services/mit-stack/backend/api/services/
ai_rule_builder.py`` from a direct ``Agent(...)`` instantiation to an
``AIAgentConfig`` lookup. Hosts flip ``is_active=true`` once an LLM key
is registered for the tenant.

The agent has *no* skills attached — it's a pure prompt-shaping LLM
call returning a JSON ``RuleCreate`` payload. Future iterations may add
``classify_intent`` (to detect decision-table vs condition-tree) but
for now the prompt instructs the LLM to make that judgement.

Idempotent: every insert is gated on ``NOT EXISTS``. Re-runnable.

Revision ID: 008_seed_rule_builder_agent
Revises: 007_seed_image_video_agents
Create Date: 2026-04-26
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable

import sqlalchemy as sa
from alembic import op

revision = "008_seed_rule_builder_agent"
down_revision = "007_seed_image_video_agents"
branch_labels = None
depends_on = None


SYSTEM_SEED_UUID = uuid.UUID("00000000-0000-0000-0000-000000000000")

AGENT_NAME = "rule_builder"
AGENT_LABEL = "Rule Builder"
AGENT_PROMPT = (
    "You are a rule-engine configuration assistant for the Mit Stack "
    "platform. The user describes a business rule in plain English. "
    "Output ONLY a valid JSON object — no markdown, no commentary — "
    "that conforms to the Mit Stack RuleCreate schema (rule_type, "
    "trigger_events, conditions, actions, else_actions, status='draft', "
    "is_active=true). The caller will set sensible defaults for any "
    "fields you omit, but prefer to be explicit. Field paths use dot "
    "notation. {{field.path}} interpolation is allowed in action "
    "values. Use rule_type='decision_table' when the description "
    "mentions a matrix / grid; otherwise rule_type='condition_tree'."
)


def _company_ids(conn) -> Iterable[uuid.UUID]:
    """Tenant lookup robust to the ``companies`` / ``company`` /
    ``organizations`` table-name drift across SentinelBuild services
    — see :func:`004_seed_builtin_skills._company_ids`."""
    insp = sa.inspect(conn)
    tables = set(insp.get_table_names())
    for candidate in ("companies", "company", "organizations"):
        if candidate in tables:
            rows = conn.execute(sa.text(f"SELECT id FROM {candidate}")).fetchall()
            return [r[0] for r in rows]
    return []


def upgrade() -> None:
    conn = op.get_bind()
    company_ids = list(_company_ids(conn))
    if not company_ids:
        return

    for cid in company_ids:
        conn.execute(
            sa.text(
                """
                INSERT INTO ai_agent_configs (
                    id, company_id, name, label, system_prompt,
                    provider_type, model_name, is_active,
                    created_by, created_at, updated_at
                )
                SELECT CAST(:id AS uuid), CAST(:cid AS uuid),
                       CAST(:name AS varchar), CAST(:label AS varchar),
                       CAST(:prompt AS text),
                       'anthropic',
                       'claude-3-5-sonnet-20240620', false,
                       CAST(:sys AS uuid), NOW(), NOW()
                WHERE NOT EXISTS (
                    SELECT 1 FROM ai_agent_configs
                    WHERE company_id = CAST(:cid AS uuid)
                      AND name = CAST(:name AS varchar)
                )
                """
            ),
            {
                "id": uuid.uuid4(),
                "cid": cid,
                "name": AGENT_NAME,
                "label": AGENT_LABEL,
                "prompt": AGENT_PROMPT,
                "sys": SYSTEM_SEED_UUID,
            },
        )


def downgrade() -> None:
    conn = op.get_bind()
    conn.execute(
        sa.text("DELETE FROM ai_agent_configs WHERE name = :name"),
        {"name": AGENT_NAME},
    )

"""Enforce unique (company_id, name) on ai_agent_configs + ai_skills.

The runtime seed (ai_seed.seed_company_ai) is idempotent, but there was no
DB-level guard against duplicate agents/skills for a company. This migration:
  1. Defensively de-dupes any existing duplicates (no-op on clean data):
     - agents: keep the copy with the most skill-links (tie-break: oldest, then id);
     - skills: re-point agent links to the survivor, then keep the oldest copy.
  2. Adds partial UNIQUE indexes so duplicates become structurally impossible.

Partial indexes (WHERE company_id IS [NOT] NULL) are used because company_id is
NULLable for scope='platform'; a plain UNIQUE wouldn't catch two platform rows
with the same name (NULLs are distinct in a standard unique index).

Idempotent.

Revision ID: 020_ai_unique_company_name
Revises: 019_agent_safety_policy
Create Date: 2026-06-08
"""

from __future__ import annotations

from alembic import op

revision = "020_ai_unique_company_name"
down_revision = "019_agent_safety_policy"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── 1) De-dupe agents: keep the most-linked copy per (company_id, name) ──
    op.execute(
        """
        WITH ranked AS (
            SELECT a.id,
                   ROW_NUMBER() OVER (
                       PARTITION BY a.company_id, a.name
                       ORDER BY (
                           SELECT count(*) FROM ai_agent_skill_links l
                            WHERE l.agent_config_id = a.id
                       ) DESC,
                       a.created_at ASC, a.id ASC
                   ) AS rn
              FROM ai_agent_configs a
        )
        DELETE FROM ai_agent_configs
         WHERE id IN (SELECT id FROM ranked WHERE rn > 1)
        """
    )

    # ── 2) De-dupe skills: re-point links to the survivor, then drop extras ──
    # Survivor = oldest row per (company_id, name).
    op.execute(
        """
        WITH ranked AS (
            SELECT s.id, s.company_id, s.name,
                   ROW_NUMBER() OVER (
                       PARTITION BY s.company_id, s.name
                       ORDER BY s.created_at ASC, s.id ASC
                   ) AS rn,
                   FIRST_VALUE(s.id) OVER (
                       PARTITION BY s.company_id, s.name
                       ORDER BY s.created_at ASC, s.id ASC
                   ) AS keeper_id
              FROM ai_skills s
        ),
        dupes AS (SELECT id, keeper_id FROM ranked WHERE rn > 1)
        UPDATE ai_agent_skill_links l
           SET skill_id = d.keeper_id
          FROM dupes d
         WHERE l.skill_id = d.id
           AND NOT EXISTS (
               SELECT 1 FROM ai_agent_skill_links e
                WHERE e.agent_config_id = l.agent_config_id
                  AND e.skill_id = d.keeper_id
           )
        """
    )
    # Drop links that would now collide with an existing (agent, keeper) link.
    op.execute(
        """
        WITH ranked AS (
            SELECT s.id,
                   ROW_NUMBER() OVER (
                       PARTITION BY s.company_id, s.name
                       ORDER BY s.created_at ASC, s.id ASC
                   ) AS rn
              FROM ai_skills s
        )
        DELETE FROM ai_skills
         WHERE id IN (SELECT id FROM ranked WHERE rn > 1)
        """
    )

    # ── 3) Partial unique indexes ───────────────────────────────────────────
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_ai_agent_configs_company_name "
        "ON ai_agent_configs (company_id, name) WHERE company_id IS NOT NULL"
    )
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_ai_agent_configs_platform_name "
        "ON ai_agent_configs (name) WHERE company_id IS NULL"
    )
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_ai_skills_company_name "
        "ON ai_skills (company_id, name) WHERE company_id IS NOT NULL"
    )
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_ai_skills_platform_name "
        "ON ai_skills (name) WHERE company_id IS NULL"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS uq_ai_skills_platform_name")
    op.execute("DROP INDEX IF EXISTS uq_ai_skills_company_name")
    op.execute("DROP INDEX IF EXISTS uq_ai_agent_configs_platform_name")
    op.execute("DROP INDEX IF EXISTS uq_ai_agent_configs_company_name")

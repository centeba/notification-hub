"""Phase G part 2 — grants tables + ``triggering_company_id`` on usage.

Adds the four supporting tables for cross-tenant agent sharing:
- ``ai_agent_grants`` — who's authorised to see/run a ``scope='shared'`` agent.
- ``ai_skill_grants`` — symmetric for skills.
- ``platform_llm_api_keys`` — platform-level LLM keys for
  ``scope='platform'`` agents (sibling of ``llm_api_keys`` minus
  ``scope_id``).
- ``ai_usage_events.triggering_company_id`` — separates "paying tenant"
  (``company_id``) from "triggering tenant" so billing reports can
  distinguish "who burnt the credit" from "who was using it".

Idempotent.

Revision ID: 014_phase_g_grants_and_triggering
Revises: 013_phase_g_scope_columns
Create Date: 2026-05-20
"""

from __future__ import annotations

from alembic import op

revision = "014_phase_g_grants_and_triggering"
down_revision = "013_phase_g_scope_columns"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── ai_agent_grants ──────────────────────────────────────────────
    # NOTE: asyncpg can't prepare multi-statement strings, so each
    # CREATE must be a separate op.execute() call.
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS ai_agent_grants (
            agent_id UUID NOT NULL
              REFERENCES ai_agent_configs(id) ON DELETE CASCADE,
            grantee_company_id UUID NOT NULL,
            pays VARCHAR(16) NOT NULL DEFAULT 'owner'
              CHECK (pays IN ('owner', 'grantee')),
            granted_by UUID NOT NULL,
            granted_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            PRIMARY KEY (agent_id, grantee_company_id)
        )
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_ai_agent_grants_grantee
            ON ai_agent_grants (grantee_company_id)
        """
    )

    # ── ai_skill_grants ──────────────────────────────────────────────
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS ai_skill_grants (
            skill_id UUID NOT NULL
              REFERENCES ai_skills(id) ON DELETE CASCADE,
            grantee_company_id UUID NOT NULL,
            pays VARCHAR(16) NOT NULL DEFAULT 'owner'
              CHECK (pays IN ('owner', 'grantee')),
            granted_by UUID NOT NULL,
            granted_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            PRIMARY KEY (skill_id, grantee_company_id)
        )
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_ai_skill_grants_grantee
            ON ai_skill_grants (grantee_company_id)
        """
    )

    # ── platform_llm_api_keys ────────────────────────────────────────
    # Sibling of llm_api_keys, minus scope_id. One row per provider —
    # the system_admin's LLM credential used to bill ``scope='platform'``
    # agent calls. ``key_encrypted`` is the host's Fernet-encrypted blob
    # (matches the existing llm_api_keys column shape).
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS platform_llm_api_keys (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            provider VARCHAR(50) NOT NULL UNIQUE,
            key_encrypted TEXT NOT NULL,
            is_active BOOLEAN NOT NULL DEFAULT TRUE,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
        """
    )

    # ── ai_usage_events.triggering_company_id ────────────────────────
    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM information_schema.columns
                 WHERE table_name = 'ai_usage_events'
                   AND column_name = 'triggering_company_id'
            ) THEN
                ALTER TABLE ai_usage_events
                  ADD COLUMN triggering_company_id UUID;
                -- Backfill: existing rows triggered themselves.
                UPDATE ai_usage_events
                   SET triggering_company_id = company_id
                 WHERE triggering_company_id IS NULL;
                ALTER TABLE ai_usage_events
                  ALTER COLUMN triggering_company_id SET NOT NULL;
                CREATE INDEX IF NOT EXISTS ix_ai_usage_events_triggering
                  ON ai_usage_events (triggering_company_id);
            END IF;
        END $$;
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_ai_usage_events_triggering")
    op.execute("ALTER TABLE ai_usage_events DROP COLUMN IF EXISTS triggering_company_id")
    op.execute("DROP TABLE IF EXISTS platform_llm_api_keys")
    op.execute("DROP TABLE IF EXISTS ai_skill_grants")
    op.execute("DROP TABLE IF EXISTS ai_agent_grants")

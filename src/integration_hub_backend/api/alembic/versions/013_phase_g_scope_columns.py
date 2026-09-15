"""Phase G part 1 — add ``scope`` columns + relax ``company_id``.

This is the first of two Phase G migrations. Split so the running app
survives the shape change: after this migration lands, all existing
rows still satisfy the existing predicates (they default to
``scope='company'`` with non-null ``company_id``, identical to the
pre-migration shape). The follow-up migration (014) adds the
grants/platform tables; this one only widens the schema.

Idempotent — uses information_schema checks so re-running against an
already-upgraded DB is a no-op.

Revision ID: 013_phase_g_scope_columns
Revises: 012_ai_agent_configs_source_app
Create Date: 2026-05-20
"""

from __future__ import annotations

from alembic import op

revision = "013_phase_g_scope_columns"
down_revision = "012_ai_agent_configs_source_app"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── ai_agent_configs ─────────────────────────────────────────────
    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM information_schema.columns
                 WHERE table_name = 'ai_agent_configs' AND column_name = 'scope'
            ) THEN
                ALTER TABLE ai_agent_configs
                  ADD COLUMN scope VARCHAR(32) NOT NULL DEFAULT 'company';
                CREATE INDEX IF NOT EXISTS ix_ai_agent_configs_scope
                  ON ai_agent_configs (scope);
                ALTER TABLE ai_agent_configs
                  ALTER COLUMN company_id DROP NOT NULL;
                ALTER TABLE ai_agent_configs
                  ADD CONSTRAINT ck_ai_agent_configs_scope_company
                  CHECK (
                    (scope = 'platform' AND company_id IS NULL)
                    OR (scope IN ('company', 'shared') AND company_id IS NOT NULL)
                  );
            END IF;
        END $$;
        """
    )

    # ── ai_skills ────────────────────────────────────────────────────
    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM information_schema.columns
                 WHERE table_name = 'ai_skills' AND column_name = 'scope'
            ) THEN
                ALTER TABLE ai_skills
                  ADD COLUMN scope VARCHAR(32) NOT NULL DEFAULT 'company';
                CREATE INDEX IF NOT EXISTS ix_ai_skills_scope
                  ON ai_skills (scope);
                ALTER TABLE ai_skills
                  ALTER COLUMN company_id DROP NOT NULL;
                ALTER TABLE ai_skills
                  ADD CONSTRAINT ck_ai_skills_scope_company
                  CHECK (
                    (scope = 'platform' AND company_id IS NULL)
                    OR (scope IN ('company', 'shared') AND company_id IS NOT NULL)
                  );
            END IF;
        END $$;
        """
    )


def downgrade() -> None:
    op.execute("ALTER TABLE ai_skills DROP CONSTRAINT IF EXISTS ck_ai_skills_scope_company")
    op.execute("DROP INDEX IF EXISTS ix_ai_skills_scope")
    op.execute("ALTER TABLE ai_skills DROP COLUMN IF EXISTS scope")
    # NOTE: ``ALTER COLUMN company_id SET NOT NULL`` is intentionally
    # NOT re-applied — by the time someone downgrades there may already
    # be platform rows with NULL company_id. The downgrade leaves the
    # column nullable to avoid data loss; a manual cleanup step is
    # required if the operator truly wants the old NOT NULL constraint.

    op.execute(
        "ALTER TABLE ai_agent_configs DROP CONSTRAINT IF EXISTS ck_ai_agent_configs_scope_company"
    )
    op.execute("DROP INDEX IF EXISTS ix_ai_agent_configs_scope")
    op.execute("ALTER TABLE ai_agent_configs DROP COLUMN IF EXISTS scope")

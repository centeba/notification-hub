"""Autonomous-agent safety harness — tool policy + run ledger + audit.

Adds:
- ``ai_agent_skill_links.approval_mode`` — per-(agent, tool) approval policy.
- ``ai_agent_configs.autonomous`` / ``max_steps`` / ``max_cost_usd`` — the
  per-agent autonomy switch + run-level caps.
- ``agent_runs`` — queryable ledger of autonomous runs (durable state lives
  in Temporal; this row is for listing/monitoring + cap enforcement).
- ``agent_action_audit`` — immutable per-tool-dispatch decision record.

Hand-written to match ``smart_llm.db.models.make_ai_models`` (the factory
columns are not autogenerate-visible). Idempotent.

Revision ID: 019_agent_safety_policy
Revises: 018_notification_system_integrations
Create Date: 2026-06-08
"""

from __future__ import annotations

from alembic import op

revision = "019_agent_safety_policy"
down_revision = "018_notification_system_integrations"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── ai_agent_skill_links.approval_mode ───────────────────────────
    op.execute(
        """
        ALTER TABLE ai_agent_skill_links
          ADD COLUMN IF NOT EXISTS approval_mode VARCHAR(16)
          NOT NULL DEFAULT 'auto'
        """
    )

    # ── ai_agent_configs autonomy switch + caps ──────────────────────
    op.execute(
        "ALTER TABLE ai_agent_configs "
        "ADD COLUMN IF NOT EXISTS autonomous BOOLEAN NOT NULL DEFAULT FALSE"
    )
    op.execute("ALTER TABLE ai_agent_configs ADD COLUMN IF NOT EXISTS max_steps INTEGER")
    op.execute("ALTER TABLE ai_agent_configs ADD COLUMN IF NOT EXISTS max_cost_usd NUMERIC(12, 4)")

    # ── agent_runs ───────────────────────────────────────────────────
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS agent_runs (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            agent_id UUID NOT NULL
              REFERENCES ai_agent_configs(id) ON DELETE CASCADE,
            acting_company_id UUID NOT NULL,
            paying_company_id UUID,
            trigger VARCHAR(64),
            status VARCHAR(32) NOT NULL DEFAULT 'running',
            step_count INTEGER NOT NULL DEFAULT 0,
            cost_usd NUMERIC(12, 4) NOT NULL DEFAULT 0,
            temporal_workflow_id VARCHAR(255),
            approvals TEXT,
            started_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            ended_at TIMESTAMPTZ
        )
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_agent_runs_agent_id ON agent_runs (agent_id)")
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_agent_runs_acting_company ON agent_runs (acting_company_id)"
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_agent_runs_status ON agent_runs (status)")

    # ── agent_action_audit ───────────────────────────────────────────
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS agent_action_audit (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            agent_run_id UUID,
            agent_id UUID NOT NULL,
            tool_name VARCHAR(128) NOT NULL,
            acting_company_id UUID NOT NULL,
            target_company_id UUID,
            paying_company_id UUID,
            decision VARCHAR(32) NOT NULL,
            reason VARCHAR(255),
            args_digest VARCHAR(64),
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_agent_action_audit_run ON agent_action_audit (agent_run_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_agent_action_audit_agent ON agent_action_audit (agent_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_agent_action_audit_acting_company "
        "ON agent_action_audit (acting_company_id)"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS agent_action_audit")
    op.execute("DROP TABLE IF EXISTS agent_runs")
    op.execute("ALTER TABLE ai_agent_configs DROP COLUMN IF EXISTS max_cost_usd")
    op.execute("ALTER TABLE ai_agent_configs DROP COLUMN IF EXISTS max_steps")
    op.execute("ALTER TABLE ai_agent_configs DROP COLUMN IF EXISTS autonomous")
    op.execute("ALTER TABLE ai_agent_skill_links DROP COLUMN IF EXISTS approval_mode")

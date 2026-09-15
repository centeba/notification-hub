"""Phase-F seed — register integration-hub MCP tools as AISkills + two
default agents per company.

Inserts one ``ai_skills`` row per registered integration-hub
:class:`ActionTool` per company (kind=python_tool, modality=text |
document), then creates two inactive :class:`AIAgentConfig`s:

- **Database Inspector** linked to
  ``[postgres_list_tables, postgres_describe_table, postgres_run_query]``
- **Inbox Triage** linked to
  ``[gmail_list, gmail_read, gmail_reply, classify_intent]``

Hosts flip the agents ``is_active=true`` once a Gmail credential or
LLM key is registered (the agents themselves still need an LLM call to
function — Phase F2 wires native function-calling).

Re-run safe: every insert is gated on ``NOT EXISTS`` keyed on
``(company_id, name)``. Mirrors migration ``004_seed_builtin_skills``
intentionally so the two seeds compose without surprises.

Revision ID: 009_seed_integration_hub_skills
Revises: 008_seed_rule_builder_agent
Create Date: 2026-04-27
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable

import sqlalchemy as sa
from alembic import op

revision = "009_seed_integration_hub_skills"
down_revision = "008_seed_rule_builder_agent"
branch_labels = None
depends_on = None


# (registry name, label, modality, description). Names MUST match the
# keys passed to ``register_tool`` in
# ``smart_llm.builtins.integration_hub.*``; the agent runtime resolves
# AISkill.name → registry lookup.
INTEGRATION_HUB_TOOLS: list[tuple[str, str, str, str]] = [
    # Postgres (3) — modality=text because results are JSON-shaped
    # records, not file blobs.
    (
        "postgres_list_tables",
        "Postgres: List Tables",
        "text",
        "List all tables in the Postgres public schema.",
    ),
    (
        "postgres_describe_table",
        "Postgres: Describe Table",
        "text",
        "Retrieve the column names and data types of a specific table.",
    ),
    (
        "postgres_run_query",
        "Postgres: Run Query",
        "text",
        "Run a raw SQL query against Postgres. SELECT only; auto-LIMIT 50.",
    ),
    # Gmail (4)
    ("gmail_send", "Gmail: Send", "text", "Send an email using a Gmail account."),
    (
        "gmail_list",
        "Gmail: List Messages",
        "text",
        "List unread or filtered messages from a Gmail account.",
    ),
    (
        "gmail_read",
        "Gmail: Read Message",
        "text",
        "Read a single Gmail message in full (headers + body) by message ID.",
    ),
    ("gmail_reply", "Gmail: Reply", "text", "Reply to an existing Gmail thread."),
    # Outlook (4)
    (
        "outlook_send",
        "Outlook: Send",
        "text",
        "Send an email using an Outlook/Microsoft 365 account.",
    ),
    (
        "outlook_list",
        "Outlook: List Messages",
        "text",
        "List messages from an Outlook/Microsoft 365 mailbox folder.",
    ),
    (
        "outlook_read",
        "Outlook: Read Message",
        "text",
        "Read a single Outlook message in full (headers + body) by message ID.",
    ),
    ("outlook_reply", "Outlook: Reply", "text", "Reply to an existing Outlook message."),
    # Drive (1) — document modality; returns file metadata.
    ("drive_list", "Google Drive: List Files", "document", "List files in a Google Drive account."),
    # Stripe (2)
    ("stripe_list_invoices", "Stripe: List Invoices", "text", "List recent Stripe invoices."),
    (
        "stripe_get_customer",
        "Stripe: Get Customer",
        "text",
        "Fetch details of a specific Stripe customer.",
    ),
    # Observability (2)
    ("datadog_query_logs", "Datadog: Query Logs", "text", "Query logs from Datadog."),
    ("elasticsearch_search", "Elasticsearch: Search", "text", "Search an Elasticsearch index."),
]

DB_INSPECTOR_SKILLS = (
    "postgres_list_tables",
    "postgres_describe_table",
    "postgres_run_query",
)
INBOX_TRIAGE_SKILLS = (
    "gmail_list",
    "gmail_read",
    "gmail_reply",
    "classify_intent",  # already seeded in migration 004
)

DB_INSPECTOR_PROMPT = (
    "You are a database introspection assistant for the SentinelBuild "
    "platform. Given a question in natural language, decide which of the "
    "available Postgres tools to call to answer it. Always prefer "
    "describe_table before run_query so generated SQL references real "
    "columns. SELECT only — never write."
)
INBOX_TRIAGE_PROMPT = (
    "You are an email triage assistant. Use the Gmail tools to list "
    "unread messages, read the body of any that look actionable, and "
    "draft a one-line summary + suggested reply. Use classify_intent to "
    "label the conversation as one of: support, sales, billing, "
    "contract, other."
)

SEED_AGENTS: list[tuple[str, str, str, tuple[str, ...]]] = [
    ("database_inspector", "Database Inspector", DB_INSPECTOR_PROMPT, DB_INSPECTOR_SKILLS),
    ("inbox_triage", "Inbox Triage", INBOX_TRIAGE_PROMPT, INBOX_TRIAGE_SKILLS),
]

# Stamp seeded rows so they're distinguishable from human-created ones.
# Mirrors the sentinel used in migration 004.
SYSTEM_SEED_UUID = uuid.UUID("00000000-0000-0000-0000-000000000000")


def _company_ids(conn) -> Iterable[uuid.UUID]:
    """Pull tenant ids — same fallback chain as migration 004."""
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
        # 1) Seed the 16 action-tool skills.
        for name, label, modality, description in INTEGRATION_HUB_TOOLS:
            conn.execute(
                sa.text(
                    """
                    INSERT INTO ai_skills (
                        id, company_id, name, label, description,
                        kind, modality, content, is_active,
                        created_by, created_at, updated_at
                    )
                    SELECT CAST(:id AS uuid), CAST(:cid AS uuid),
                           CAST(:name AS varchar), CAST(:label AS varchar),
                           CAST(:description AS text),
                           'python_tool', CAST(:modality AS varchar),
                           NULL, true,
                           CAST(:sys AS uuid), NOW(), NOW()
                    WHERE NOT EXISTS (
                        SELECT 1 FROM ai_skills
                        WHERE company_id = CAST(:cid AS uuid)
                          AND name = CAST(:name AS varchar)
                    )
                    """
                ),
                {
                    "id": uuid.uuid4(),
                    "cid": cid,
                    "name": name,
                    "label": label,
                    "description": description,
                    "modality": modality,
                    "sys": SYSTEM_SEED_UUID,
                },
            )

        # 2) Seed the two inactive agents.
        for agent_name, agent_label, agent_prompt, agent_skills in SEED_AGENTS:
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
                    "name": agent_name,
                    "label": agent_label,
                    "prompt": agent_prompt,
                    "sys": SYSTEM_SEED_UUID,
                },
            )

            row = conn.execute(
                sa.text("SELECT id FROM ai_agent_configs WHERE company_id = :cid AND name = :name"),
                {"cid": cid, "name": agent_name},
            ).fetchone()
            if row is None:
                continue
            agent_id = row[0]

            for skill_name in agent_skills:
                conn.execute(
                    sa.text(
                        """
                        INSERT INTO ai_agent_skill_links (agent_config_id, skill_id)
                        SELECT CAST(:aid AS uuid), s.id
                        FROM ai_skills s
                        WHERE s.company_id = CAST(:cid AS uuid)
                          AND s.name = CAST(:sname AS varchar)
                          AND NOT EXISTS (
                              SELECT 1 FROM ai_agent_skill_links l
                              WHERE l.agent_config_id = CAST(:aid AS uuid)
                                AND l.skill_id = s.id
                          )
                        """
                    ),
                    {"aid": agent_id, "cid": cid, "sname": skill_name},
                )


def downgrade() -> None:
    conn = op.get_bind()
    seeded_names = tuple(name for name, *_ in SEED_AGENTS)
    agent_placeholders = ", ".join(f"'{n}'" for n in seeded_names)
    conn.execute(
        sa.text(
            f"DELETE FROM ai_agent_skill_links "
            f"WHERE agent_config_id IN ("
            f"  SELECT id FROM ai_agent_configs WHERE name IN ({agent_placeholders})"
            f")"
        )
    )
    conn.execute(sa.text(f"DELETE FROM ai_agent_configs WHERE name IN ({agent_placeholders})"))
    skill_names = ", ".join(f"'{t[0]}'" for t in INTEGRATION_HUB_TOOLS)
    conn.execute(
        sa.text(f"DELETE FROM ai_skills WHERE name IN ({skill_names}) AND kind = 'python_tool'")
    )

"""Attach the missing skills to Rule Builder + Document Triage agents.

The seeded ``rule_builder`` (migration 008) and
``document_triage_template`` (migration 006) agents were created
without any attached skills — they were placeholders for the
underlying tools that this migration now ships.

Adds 4 new ``ai_skills`` rows per company and links them to their
parent agent:

- Rule Builder gets:
    * ``list_notification_rules``        (kind=python_tool, ActionTool)
    * ``list_notification_event_types``  (kind=python_tool, ActionTool)
    * ``create_notification_rule``       (kind=python_tool, ActionTool)
- Document Triage Template gets:
    * ``document_triage_orchestrator``   (kind=prompt, Tool)

Re-run safe via ``NOT EXISTS`` checks; mirrors migrations 004 / 009.

Revision ID: 010_attach_rule_builder_and_triage_skills
Revises: 009_seed_integration_hub_skills
Create Date: 2026-04-27
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable

import sqlalchemy as sa
from alembic import op

revision = "010_attach_rule_skills"
down_revision = "009_seed_integration_hub_skills"
branch_labels = None
depends_on = None


# (name, label, kind, modality, description). Names MUST match the
# smart_llm.registry keys exactly.
NEW_SKILLS: list[tuple[str, str, str, str, str]] = [
    (
        "list_notification_rules",
        "Rules: List Notification Rules",
        "python_tool",
        "text",
        "List notification rules configured for a company.",
    ),
    (
        "list_notification_event_types",
        "Rules: List Event Types",
        "python_tool",
        "text",
        "List the catalogue of event types (rule triggers) for a company. "
        "Use before create_notification_rule.",
    ),
    (
        "create_notification_rule",
        "Rules: Create Notification Rule",
        "python_tool",
        "text",
        "Create a notification rule binding an event_type to channels via "
        "a template, with optional conditions and recipient strategy.",
    ),
    (
        "document_triage_orchestrator",
        "Document Triage Orchestrator",
        "prompt",
        "document",
        "Top-level routing prompt for the Document Triage agent — "
        "classifies intent then routes through downstream skills.",
    ),
]

RULE_BUILDER_SKILLS = (
    "list_notification_rules",
    "list_notification_event_types",
    "create_notification_rule",
)
DOCUMENT_TRIAGE_SKILLS = ("document_triage_orchestrator",)

# Stamp seeded rows so they're distinguishable from human-created
# ones. Same sentinel as migrations 004 / 009.
SYSTEM_SEED_UUID = uuid.UUID("00000000-0000-0000-0000-000000000000")


def _company_ids(conn) -> Iterable[uuid.UUID]:
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
        # 1) Insert the 4 skills (idempotent on (company_id, name)).
        for name, label, kind, modality, description in NEW_SKILLS:
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
                           CAST(:kind AS varchar), CAST(:modality AS varchar),
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
                    "kind": kind,
                    "modality": modality,
                    "sys": SYSTEM_SEED_UUID,
                },
            )

        # 2) Link skills to their parent agents.
        for agent_name, skills in (
            ("rule_builder", RULE_BUILDER_SKILLS),
            ("document_triage_template", DOCUMENT_TRIAGE_SKILLS),
        ):
            row = conn.execute(
                sa.text("SELECT id FROM ai_agent_configs WHERE company_id = :cid AND name = :name"),
                {"cid": cid, "name": agent_name},
            ).fetchone()
            if row is None:
                # Agent not seeded for this company — skip silently.
                continue
            agent_id = row[0]

            for skill_name in skills:
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
    skill_names = ", ".join(f"'{n}'" for n, *_ in NEW_SKILLS)
    # Drop the links first, then the skill rows themselves.
    conn.execute(
        sa.text(
            f"DELETE FROM ai_agent_skill_links "
            f"WHERE skill_id IN ("
            f"  SELECT id FROM ai_skills WHERE name IN ({skill_names})"
            f")"
        )
    )
    conn.execute(sa.text(f"DELETE FROM ai_skills WHERE name IN ({skill_names})"))

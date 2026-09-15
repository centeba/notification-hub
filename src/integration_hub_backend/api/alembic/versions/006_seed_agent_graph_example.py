"""Phase-E2 follow-up — seed a "Document Triage" agent graph example.

Creates four inactive ``AIAgentConfig`` rows per company:

- ``triage_classifier`` (skill: ``classify_intent``)
- ``triage_tagger`` (skill: ``tag_document``)
- ``triage_summarizer`` (skill: ``summarize``)
- ``triage_extractor`` (skill: ``extract_entities``)

…then writes a 5th meta agent ``document_triage_template`` whose
``system_prompt`` holds the assembled :class:`AgentGraphSpec` JSON
with the actual UUIDs of the four leaf agents filled in. The
workflow-builder's ``agent_graph_node`` config form reads this
prompt to offer a "Copy from Document Triage" starter spec, so
authors don't have to hand-author UUIDs.

Idempotent — every insert is gated on ``NOT EXISTS``.

Revision ID: 006_seed_agent_graph_example
Revises: 005_ai_usage_events
Create Date: 2026-04-25
"""

from __future__ import annotations

import json
import uuid

import sqlalchemy as sa
from alembic import op

revision = "006_seed_agent_graph_example"
down_revision = "005_ai_usage_events"
branch_labels = None
depends_on = None


# (agent_name, label, prompt, skill_name)
LEAF_AGENTS: list[tuple[str, str, str, str]] = [
    (
        "triage_classifier",
        "Triage: Classifier",
        "Classify the input text. Return JSON with an 'intent' field "
        "set to one of: tag, summary, entities. No commentary.",
        "classify_intent",
    ),
    (
        "triage_tagger",
        "Triage: Tagger",
        "Tag the input document. Return JSON with 'tags' and 'tag_confidence'.",
        "tag_document",
    ),
    (
        "triage_summarizer",
        "Triage: Summarizer",
        "Summarise the input. Return JSON with 'summary' (string).",
        "summarize",
    ),
    (
        "triage_extractor",
        "Triage: Entity Extractor",
        "Extract named entities. Return JSON with 'entities' (array).",
        "extract_entities",
    ),
]


# Same sentinel as migration 004 — keeps seeded rows attributable.
SYSTEM_SEED_UUID = uuid.UUID("00000000-0000-0000-0000-000000000000")


def _company_ids(conn):
    """Tenant lookup that copes with the historical table-name drift —
    see :func:`004_seed_builtin_skills._company_ids` for context."""
    insp = sa.inspect(conn)
    tables = set(insp.get_table_names())
    for candidate in ("companies", "company", "organizations"):
        if candidate in tables:
            return [r[0] for r in conn.execute(sa.text(f"SELECT id FROM {candidate}")).fetchall()]
    return []


def _upsert_agent(conn, *, cid, name, label, prompt) -> uuid.UUID:
    """Return the UUID of the agent (existing or newly inserted)."""
    row = conn.execute(
        sa.text("SELECT id FROM ai_agent_configs WHERE company_id = :cid AND name = :name"),
        {"cid": cid, "name": name},
    ).fetchone()
    if row is not None:
        return row[0]
    new_id = uuid.uuid4()
    conn.execute(
        sa.text(
            """
            INSERT INTO ai_agent_configs (
                id, company_id, name, label, system_prompt,
                provider_type, model_name, is_active,
                created_by, created_at, updated_at
            )
            VALUES (
                CAST(:id AS uuid), CAST(:cid AS uuid),
                CAST(:name AS varchar), CAST(:label AS varchar),
                CAST(:prompt AS text),
                'anthropic', 'claude-3-5-sonnet-20240620', false,
                CAST(:sys AS uuid), NOW(), NOW()
            )
            """
        ),
        {
            "id": new_id,
            "cid": cid,
            "name": name,
            "label": label,
            "prompt": prompt,
            "sys": SYSTEM_SEED_UUID,
        },
    )
    return new_id


def _link_skill(conn, *, cid, agent_id, skill_name) -> None:
    """Link an agent → skill via the (agent_config_id, skill_id) composite PK
    table created by migration 003."""
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
                  WHERE l.agent_config_id = CAST(:aid AS uuid) AND l.skill_id = s.id
              )
            """
        ),
        {
            "aid": agent_id,
            "cid": cid,
            "sname": skill_name,
        },
    )


def upgrade() -> None:
    conn = op.get_bind()
    for cid in _company_ids(conn):
        leaf_ids: dict[str, uuid.UUID] = {}
        for name, label, prompt, skill_name in LEAF_AGENTS:
            aid = _upsert_agent(conn, cid=cid, name=name, label=label, prompt=prompt)
            _link_skill(conn, cid=cid, agent_id=aid, skill_name=skill_name)
            leaf_ids[name] = aid

        # Build the AgentGraphSpec template with real UUIDs. Branch
        # predicates match :func:`smart_llm.orchestrator._branch_matches`
        # — the upstream classifier returns ``{"intent": ...}`` and
        # each downstream node fires only when its predicate matches.
        spec = {
            "entry": "classify",
            "nodes": [
                {
                    "id": "classify",
                    "agent_id": str(leaf_ids["triage_classifier"]),
                    "next": ["tag", "summarize", "extract"],
                },
                {
                    "id": "tag",
                    "agent_id": str(leaf_ids["triage_tagger"]),
                    "branch": "intent==tag",
                    "next": [],
                },
                {
                    "id": "summarize",
                    "agent_id": str(leaf_ids["triage_summarizer"]),
                    "branch": "intent==summary",
                    "next": [],
                },
                {
                    "id": "extract",
                    "agent_id": str(leaf_ids["triage_extractor"]),
                    "branch": "intent==entities",
                    "next": [],
                },
            ],
        }
        prompt = (
            "[AgentGraphSpec template — paste this into an "
            "``agent_graph_node`` config to triage documents:]\n\n" + json.dumps(spec, indent=2)
        )
        _upsert_agent(
            conn,
            cid=cid,
            name="document_triage_template",
            label="Document Triage (template)",
            prompt=prompt,
        )


def downgrade() -> None:
    conn = op.get_bind()
    names = [n for n, *_ in LEAF_AGENTS] + ["document_triage_template"]
    placeholders = ", ".join(f"'{n}'" for n in names)
    conn.execute(
        sa.text(
            f"DELETE FROM ai_agent_skill_links "
            f"WHERE agent_config_id IN ("
            f"  SELECT id FROM ai_agent_configs WHERE name IN ({placeholders})"
            f")"
        )
    )
    conn.execute(sa.text(f"DELETE FROM ai_agent_configs WHERE name IN ({placeholders})"))

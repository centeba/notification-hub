"""Seed dedicated image / video tagger + summariser agents.

Adds the two new builtin skills introduced alongside this migration:

- ``classify_image`` (modality: ``image``) — vision-only classifier
  returning an ``image_kind`` JSON object.
- ``summarize_video`` (modality: ``video``) — transcribe then ask
  the LLM for a structured narrative summary.

…then seeds two inactive ``AIAgentConfig`` rows per company:

- ``image_tagger`` — chained skills:
  ``[parse_image_ocr, classify_image, generate_tags, auto_create_tag]``
- ``video_tagger`` — chained skills:
  ``[parse_video_transcript, summarize_video, generate_tags, auto_create_tag]``

Both agents are seeded ``is_active=false``; the host's AI Admin flips
them on once an LLM key is registered for the relevant provider.

Idempotent — every insert is gated on ``NOT EXISTS``. Casts on bound
parameters mirror migrations 004/006 to keep asyncpg's prepared-
statement type deduction happy.

Revision ID: 007_seed_image_video_agents
Revises: 006_seed_agent_graph_example
Create Date: 2026-04-26
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable

import sqlalchemy as sa
from alembic import op

revision = "007_seed_image_video_agents"
down_revision = "006_seed_agent_graph_example"
branch_labels = None
depends_on = None


SYSTEM_SEED_UUID = uuid.UUID("00000000-0000-0000-0000-000000000000")

# (name, label, modality, description) — same shape as 004's BUILTINS.
NEW_BUILTINS: list[tuple[str, str, str, str]] = [
    (
        "classify_image",
        "Classify Image",
        "image",
        "Vision-LLM image classifier — returns image_kind, subject, "
        "description, contains_text, confidence as JSON.",
    ),
    (
        "summarize_video",
        "Summarize Video",
        "video",
        "Transcribe a video then ask the LLM for a narrative summary "
        "with key_moments and dominant_topics.",
    ),
]


IMAGE_TAGGER_SKILLS = (
    "parse_image_ocr",
    "classify_image",
    "generate_tags",
    "auto_create_tag",
)
VIDEO_TAGGER_SKILLS = (
    "parse_video_transcript",
    "summarize_video",
    "generate_tags",
    "auto_create_tag",
)

IMAGE_TAGGER_PROMPT = (
    "You are an image classification + tagging assistant. The input "
    "carries either OCR-recovered text, a vision-LLM JSON description, "
    "or both. Reply with strict JSON containing 'tags' (3-8 lowercase "
    "kebab-case strings) and 'tag_confidence' (object keyed by tag, "
    "values 0.0-1.0). When a classify_image result is present, mention "
    "its image_kind in one of the tags."
)
VIDEO_TAGGER_PROMPT = (
    "You are a video summarisation + tagging assistant. The input "
    "begins with a video transcript or frame description, often "
    "followed by a summarize_video JSON block. Reply with strict JSON "
    "containing 'tags' (3-8 lowercase kebab-case strings) and "
    "'tag_confidence' (object keyed by tag, values 0.0-1.0) describing "
    "the video's subject and content."
)

# (agent_name, label, system_prompt, [skill_names])
SEED_AGENTS: list[tuple[str, str, str, tuple[str, ...]]] = [
    ("image_tagger", "Image Tagger", IMAGE_TAGGER_PROMPT, IMAGE_TAGGER_SKILLS),
    ("video_tagger", "Video Tagger", VIDEO_TAGGER_PROMPT, VIDEO_TAGGER_SKILLS),
]


def _company_ids(conn) -> Iterable[uuid.UUID]:
    """Tenant lookup robust to the table-name drift between SentinelBuild
    services — see :func:`004_seed_builtin_skills._company_ids`."""
    insp = sa.inspect(conn)
    tables = set(insp.get_table_names())
    for candidate in ("companies", "company", "organizations"):
        if candidate in tables:
            rows = conn.execute(sa.text(f"SELECT id FROM {candidate}")).fetchall()
            return [r[0] for r in rows]
    return []


def upgrade() -> None:
    conn = op.get_bind()

    # Rename mis-seeded rows from migration 004. The registry keys are
    # ``parse_video_transcript`` / ``parse_audio_transcript``; 004
    # originally seeded the row names without the ``_transcript``
    # suffix, so any agent linking to those rows would fail to resolve
    # at runtime. The UPDATE is idempotent — already-renamed rows are
    # filtered out by the ``WHERE`` clause.
    conn.execute(
        sa.text(
            "UPDATE ai_skills SET name='parse_video_transcript' "
            "WHERE name='parse_video' AND kind='python_tool'"
        )
    )
    conn.execute(
        sa.text(
            "UPDATE ai_skills SET name='parse_audio_transcript' "
            "WHERE name='parse_audio' AND kind='python_tool'"
        )
    )

    company_ids = list(_company_ids(conn))
    if not company_ids:
        return

    for cid in company_ids:
        # 1) Seed the two new skill rows.
        for name, label, modality, description in NEW_BUILTINS:
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

        # 2) Seed the two new agents.
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

            # 3) Link skills via composite-PK link table.
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
                    {
                        "aid": agent_id,
                        "cid": cid,
                        "sname": skill_name,
                    },
                )


def downgrade() -> None:
    conn = op.get_bind()
    seeded_agents = tuple(name for name, *_ in SEED_AGENTS)
    seeded_skills = tuple(b[0] for b in NEW_BUILTINS)
    a_placeholders = ", ".join(f"'{n}'" for n in seeded_agents)
    s_placeholders = ", ".join(f"'{n}'" for n in seeded_skills)
    conn.execute(
        sa.text(
            f"DELETE FROM ai_agent_skill_links "
            f"WHERE agent_config_id IN ("
            f"  SELECT id FROM ai_agent_configs WHERE name IN ({a_placeholders})"
            f")"
        )
    )
    conn.execute(sa.text(f"DELETE FROM ai_agent_configs WHERE name IN ({a_placeholders})"))
    conn.execute(
        sa.text(f"DELETE FROM ai_skills WHERE name IN ({s_placeholders}) AND kind = 'python_tool'")
    )

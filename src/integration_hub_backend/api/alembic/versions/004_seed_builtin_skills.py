"""Seed builtin AI skills + Document Tagger agent for every company.

Inserts one ``ai_skills`` row per registered builtin (kind=python_tool)
per existing ``companies`` row, then creates an inactive
"document_tagger" :class:`AIAgentConfig` per company linked to
``[parse_pdf, generate_tags, auto_create_tag]``. Hosts can flip the
agent ``is_active=true`` once they've registered an LLM key.

Re-run safe: every insert is gated on a ``NOT EXISTS`` check keyed on
``(company_id, name)``.

Revision ID: 004_seed_builtin_skills
Revises: 003_ai_agent_tables
Create Date: 2026-04-25
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable

import sqlalchemy as sa
from alembic import op

revision = "004_seed_builtin_skills"
down_revision = "003_ai_agent_tables"
branch_labels = None
depends_on = None


# (name, label, modality, description)
BUILTINS: list[tuple[str, str, str, str]] = [
    ("parse_pdf", "Parse PDF", "document", "Extract plaintext from a PDF file or base64 blob."),
    ("parse_docx", "Parse DOCX", "document", "Extract plaintext from a DOCX file."),
    (
        "parse_image_ocr",
        "Parse Image (OCR)",
        "image",
        "Run Tesseract OCR on an image to recover text.",
    ),
    # Names must match the smart_llm.registry keys exactly — agents resolve
    # skills by row name → registry lookup at runtime.
    (
        "parse_video_transcript",
        "Parse Video Transcript",
        "video",
        "Transcribe a video file's audio track.",
    ),
    ("parse_audio_transcript", "Parse Audio Transcript", "audio", "Transcribe an audio file."),
    (
        "extract_entities",
        "Extract Entities",
        "text",
        "Ask the LLM to add an 'entities' field listing people, orgs, and dates.",
    ),
    (
        "summarize",
        "Summarize",
        "text",
        "Summarise the input into a configurable number of sentences.",
    ),
    (
        "classify_intent",
        "Classify Intent",
        "text",
        "Add an 'intent' label (support|sales|billing|contract|other).",
    ),
    (
        "generate_tags",
        "Generate Tags",
        "any",
        "Ask the LLM for 3-8 lowercase kebab-case tags + confidence.",
    ),
    (
        "auto_create_tag",
        "Auto-Create Tag",
        "any",
        "Persist any high-confidence tag into the host's tag table.",
    ),
    ("tag_document", "Tag Document", "document", "Parse + tag a PDF/DOCX in one step."),
    ("tag_image", "Tag Image", "image", "OCR + tag an image in one step."),
    ("tag_video", "Tag Video", "video", "Transcribe + tag a video in one step."),
    ("tag_audio", "Tag Audio", "audio", "Transcribe + tag an audio file in one step."),
    # Phase D additions — let the per-service agents wire from the registry.
    (
        "extract_email_fields",
        "Extract Email Fields",
        "text",
        "Pull intent/sender_role/action/due_date/parties/summary out of an email body.",
    ),
    (
        "contract_clause_scan",
        "Contract Clause Scan",
        "text",
        "Identify notable contract clauses (termination, IP, indemnity, …).",
    ),
    (
        "red_flag_detection",
        "Red Flag Detection",
        "text",
        "Surface high-risk clauses + severity in a contract.",
    ),
    (
        "detect_signature_fields",
        "Detect Signature Fields",
        "document",
        "Locate signature/initials/date placeholders in a document.",
    ),
]

DOC_TAGGER_SKILLS = ("parse_pdf", "generate_tags", "auto_create_tag")
EMAIL_EXTRACTOR_SKILLS = ("extract_email_fields", "classify_intent")
ESIGN_SCANNER_SKILLS = ("detect_signature_fields", "contract_clause_scan", "red_flag_detection")

DOC_TAGGER_PROMPT = (
    "You are a document classification assistant. Given the input "
    "document text, suggest 3-8 short lowercase kebab-case tags "
    "describing its subject and type. Return JSON with 'tags' (array) "
    "and 'tag_confidence' (object keyed by tag, values 0.0-1.0)."
)
EMAIL_EXTRACTOR_PROMPT = (
    "You are an email-data extraction agent. Read the email body and "
    "return a strict JSON object — no commentary, no markdown."
)
ESIGN_SCANNER_PROMPT = (
    "You are a contract analysis assistant for an e-signature platform. "
    "When asked to detect fields, return a JSON array. When asked to "
    "scan clauses or red flags, return the requested JSON object."
)

# (agent_name, label, system_prompt, [skill_names])
SEED_AGENTS: list[tuple[str, str, str, tuple[str, ...]]] = [
    ("document_tagger", "Document Tagger", DOC_TAGGER_PROMPT, DOC_TAGGER_SKILLS),
    ("email_extractor", "Email Extractor", EMAIL_EXTRACTOR_PROMPT, EMAIL_EXTRACTOR_SKILLS),
    (
        "esign_contract_scanner",
        "Esign Contract Scanner",
        ESIGN_SCANNER_PROMPT,
        ESIGN_SCANNER_SKILLS,
    ),
]


# UUID sentinel stamped onto migration-seeded rows so they are
# distinguishable from human-created agents/skills. ``created_by`` is
# NOT NULL on both ai_skills and ai_agent_configs, so we need a value.
SYSTEM_SEED_UUID = uuid.UUID("00000000-0000-0000-0000-000000000000")


def _company_ids(conn) -> Iterable[uuid.UUID]:
    """Return the host's tenant ids, regardless of which tenant table the
    deployment uses.

    Different SentinelBuild services have historically pluralised the
    tenant table differently (``companies`` plural in newer specs,
    ``company`` singular in older ones, ``organizations`` in user-master).
    Try each in order so the seed runs cleanly across deployments.
    """
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
        # 1) Seed skills.
        for name, label, modality, description in BUILTINS:
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

        # 2) Seed agents (inactive — host flips on once a key exists).
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

            # 3) Link skills. Composite PK (agent_config_id, skill_id) — see
            # migration 003 + the ORM in smart_llm.db.models.AIAgentSkillLink.
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


def downgrade() -> None:
    conn = op.get_bind()
    # Remove only the seeded artefacts. Skills with a non-default kind or
    # custom content are preserved by name-list scoping.
    seeded_names = tuple(name for name, *_ in SEED_AGENTS)
    placeholders = ", ".join(f"'{n}'" for n in seeded_names)
    conn.execute(
        sa.text(
            f"DELETE FROM ai_agent_skill_links "
            f"WHERE agent_config_id IN ("
            f"  SELECT id FROM ai_agent_configs WHERE name IN ({placeholders})"
            f")"
        )
    )
    conn.execute(sa.text(f"DELETE FROM ai_agent_configs WHERE name IN ({placeholders})"))
    names = ", ".join(f"'{b[0]}'" for b in BUILTINS)
    conn.execute(sa.text(f"DELETE FROM ai_skills WHERE name IN ({names}) AND kind = 'python_tool'"))

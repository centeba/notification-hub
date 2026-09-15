"""Re-runnable AI skill / agent seeder for a single company.

The alembic migrations (004, 006, 007) seed the same shape against
*every existing* company at upgrade time. New tenants created after
the migration ran would otherwise have no AI skills/agents until the
next ``alembic upgrade`` — which is unnecessary because the seed is
idempotent and cheap.

This module exposes :func:`seed_ai_for_company`, an async helper that
runs the same INSERTs the migrations do (gated on ``NOT EXISTS``) for
one company. Wire it into the company-creation hook (e.g. user-master
``crud.create_company`` cross-service call, or a domain event
listener) so freshly-provisioned tenants land with the same default
toolbelt.

The data here is intentionally a literal copy of the migration data
rather than an import from the alembic revision modules — alembic
revisions are point-in-time snapshots and should not be imported as
runtime code. When a new builtin / agent is added:

1. Add it to the next alembic data-migration file.
2. Mirror it in the lists below.

The two stay in sync the same way ORM models and migration columns
stay in sync — by convention and review.
"""

from __future__ import annotations

import logging
import uuid

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

log = logging.getLogger(__name__)

SYSTEM_SEED_UUID = uuid.UUID("00000000-0000-0000-0000-000000000000")


# ── data — kept in sync with migrations 004, 007 ───────────────────────────

# (name, label, modality, description) — superset of migrations 004 + 007.
_BUILTINS: list[tuple[str, str, str, str]] = [
    ("parse_pdf", "Parse PDF", "document", "Extract plaintext from a PDF file or base64 blob."),
    ("parse_docx", "Parse DOCX", "document", "Extract plaintext from a DOCX file."),
    (
        "parse_image_ocr",
        "Parse Image (OCR)",
        "image",
        "Run Tesseract OCR on an image to recover text.",
    ),
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
    # 007 additions
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


_DOC_TAGGER_PROMPT = (
    "You are a document classification assistant. Given the input "
    "document text, suggest 3-8 short lowercase kebab-case tags "
    "describing its subject and type. Return JSON with 'tags' (array) "
    "and 'tag_confidence' (object keyed by tag, values 0.0-1.0)."
)
_EMAIL_EXTRACTOR_PROMPT = (
    "You are an email-data extraction agent. Read the email body and "
    "return a strict JSON object — no commentary, no markdown."
)
_ESIGN_SCANNER_PROMPT = (
    "You are a contract analysis assistant for an e-signature platform. "
    "When asked to detect fields, return a JSON array. When asked to "
    "scan clauses or red flags, return the requested JSON object."
)
_IMAGE_TAGGER_PROMPT = (
    "You are an image classification + tagging assistant. The input "
    "carries either OCR-recovered text, a vision-LLM JSON description, "
    "or both. Reply with strict JSON containing 'tags' (3-8 lowercase "
    "kebab-case strings) and 'tag_confidence' (object keyed by tag, "
    "values 0.0-1.0). When a classify_image result is present, mention "
    "its image_kind in one of the tags."
)
_VIDEO_TAGGER_PROMPT = (
    "You are a video summarisation + tagging assistant. The input "
    "begins with a video transcript or frame description, often "
    "followed by a summarize_video JSON block. Reply with strict JSON "
    "containing 'tags' (3-8 lowercase kebab-case strings) and "
    "'tag_confidence' (object keyed by tag, values 0.0-1.0) describing "
    "the video's subject and content."
)
# Phase D follow-up — backs services/mit-stack/backend/api/services/
# ai_rule_builder.py so the rule-builder LLM call routes through an
# AIAgentConfig (and the per-tenant KeyManager) instead of reading
# settings.anthropic_api_key directly.
_RULE_BUILDER_PROMPT = (
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

# (agent_name, label, system_prompt, [skill_names])
_SEED_AGENTS: list[tuple[str, str, str, tuple[str, ...]]] = [
    (
        "document_tagger",
        "Document Tagger",
        _DOC_TAGGER_PROMPT,
        ("parse_pdf", "generate_tags", "auto_create_tag"),
    ),
    (
        "email_extractor",
        "Email Extractor",
        _EMAIL_EXTRACTOR_PROMPT,
        ("extract_email_fields", "classify_intent"),
    ),
    (
        "esign_contract_scanner",
        "Esign Contract Scanner",
        _ESIGN_SCANNER_PROMPT,
        ("detect_signature_fields", "contract_clause_scan", "red_flag_detection"),
    ),
    (
        "image_tagger",
        "Image Tagger",
        _IMAGE_TAGGER_PROMPT,
        ("parse_image_ocr", "classify_image", "generate_tags", "auto_create_tag"),
    ),
    (
        "video_tagger",
        "Video Tagger",
        _VIDEO_TAGGER_PROMPT,
        ("parse_video_transcript", "summarize_video", "generate_tags", "auto_create_tag"),
    ),
    # No skills — rule_builder is a pure prompt-shaping LLM call that
    # returns JSON; it doesn't chain through any builtin tools.
    ("rule_builder", "Rule Builder", _RULE_BUILDER_PROMPT, ()),
]


# ── public API ─────────────────────────────────────────────────────────────


async def seed_ai_for_company(session: AsyncSession, company_id: uuid.UUID) -> dict[str, int]:
    """Seed the default AI skills + agents + skill links for one company.

    Idempotent — every INSERT is gated on ``NOT EXISTS``. Safe to call
    on every company-creation event regardless of whether the migrations
    already seeded this tenant.

    Returns a small report: ``{"skills_seeded": int, "agents_seeded":
    int, "links_seeded": int}``. Useful for an audit log entry on the
    caller side.
    """
    skills_before = await _count_skills(session, company_id)
    agents_before = await _count_agents(session, company_id)
    links_before = await _count_links(session, company_id)

    for name, label, modality, description in _BUILTINS:
        await session.execute(
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
                "cid": company_id,
                "name": name,
                "label": label,
                "description": description,
                "modality": modality,
                "sys": SYSTEM_SEED_UUID,
            },
        )

    for agent_name, agent_label, agent_prompt, agent_skills in _SEED_AGENTS:
        await session.execute(
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
                "cid": company_id,
                "name": agent_name,
                "label": agent_label,
                "prompt": agent_prompt,
                "sys": SYSTEM_SEED_UUID,
            },
        )

        # Resolve the agent id (whether we just inserted it or it already
        # existed) so we can attach skill links.
        row = (
            await session.execute(
                sa.text(
                    "SELECT id FROM ai_agent_configs "
                    "WHERE company_id = CAST(:cid AS uuid) "
                    "AND name = CAST(:name AS varchar)"
                ),
                {"cid": company_id, "name": agent_name},
            )
        ).fetchone()
        if row is None:
            continue
        agent_id = row[0]

        for skill_name in agent_skills:
            await session.execute(
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
                    "cid": company_id,
                    "sname": skill_name,
                },
            )

    await session.commit()

    skills_after = await _count_skills(session, company_id)
    agents_after = await _count_agents(session, company_id)
    links_after = await _count_links(session, company_id)

    report = {
        "skills_seeded": skills_after - skills_before,
        "agents_seeded": agents_after - agents_before,
        "links_seeded": links_after - links_before,
    }
    log.info("seed_ai_for_company company=%s %s", company_id, report)
    return report


# ── helpers ────────────────────────────────────────────────────────────────


async def _count_skills(session: AsyncSession, cid: uuid.UUID) -> int:
    row = (
        await session.execute(
            sa.text("SELECT count(*) FROM ai_skills WHERE company_id = CAST(:cid AS uuid)"),
            {"cid": cid},
        )
    ).fetchone()
    return int(row[0]) if row else 0


async def _count_agents(session: AsyncSession, cid: uuid.UUID) -> int:
    row = (
        await session.execute(
            sa.text("SELECT count(*) FROM ai_agent_configs WHERE company_id = CAST(:cid AS uuid)"),
            {"cid": cid},
        )
    ).fetchone()
    return int(row[0]) if row else 0


async def _count_links(session: AsyncSession, cid: uuid.UUID) -> int:
    row = (
        await session.execute(
            sa.text(
                "SELECT count(*) FROM ai_agent_skill_links l "
                "JOIN ai_agent_configs a ON a.id = l.agent_config_id "
                "WHERE a.company_id = CAST(:cid AS uuid)"
            ),
            {"cid": cid},
        )
    ).fetchone()
    return int(row[0]) if row else 0

"""Compatibility shim — AI agent models now live in smart-llm.

The ORM classes (``AISkill``, ``AIAgentConfig``, ``AIAgentSkillLink``) are
built by :func:`smart_llm.db.make_ai_models` against this host's
declarative ``Base`` so the tables remain in integration-hub's metadata
and Alembic continues to manage them. Pydantic schemas are imported
directly from smart-llm.

Existing imports of the form
``from integration_hub_backend.api.models.ai_agent import AISkill``
continue to work via the re-exports below.
"""

from __future__ import annotations

from smart_llm.db import (
    MODALITIES,
    MODALITY_ANY,
    MODALITY_AUDIO,
    MODALITY_DOCUMENT,
    MODALITY_IMAGE,
    MODALITY_TEXT,
    MODALITY_VIDEO,
    SKILL_KIND_PROMPT,
    SKILL_KIND_PYTHON_TOOL,
    SKILL_KINDS,
    AIAgentConfigCreate,
    AIAgentConfigPublic,
    AIAgentConfigsPublic,
    AIAgentConfigUpdate,
    AIAgentSyncItem,
    AIAgentSyncRequest,
    AIAgentSyncResponse,
    AIAgentSyncResultItem,
    AISkillCreate,
    AISkillPublic,
    AISkillsPublic,
    AISkillSyncItem,
    AISkillSyncRequest,
    AISkillSyncResponse,
    AISkillSyncResultItem,
    AISkillUpdate,
    CompanyLLMApiKeyCreate,
    CompanyLLMApiKeyPublic,
    CompanyLLMApiKeysPublic,
    Message,
    make_ai_models,
)

from integration_hub_backend.api.core.db import Base

# Build ORM classes once, bound to this host's Base.
_models = make_ai_models(Base)
AISkill = _models["AISkill"]
AIAgentConfig = _models["AIAgentConfig"]
AIAgentSkillLink = _models["AIAgentSkillLink"]
# Phase G — grants tables (created by migrations 013 + 014). Re-exported
# so the routers + AIService can pass them through to smart-llm.
AIAgentGrant = _models["AIAgentGrant"]
AISkillGrant = _models["AISkillGrant"]
# Autonomous-agent safety harness (migration 019). Re-exported so the
# tool-policy gate + agent-run endpoints can persist runs + action audit.
AgentRun = _models["AgentRun"]
AgentActionAudit = _models["AgentActionAudit"]

__all__ = [
    "MODALITIES",
    "MODALITY_ANY",
    "MODALITY_AUDIO",
    "MODALITY_DOCUMENT",
    "MODALITY_IMAGE",
    "MODALITY_TEXT",
    "MODALITY_VIDEO",
    "SKILL_KINDS",
    "SKILL_KIND_PROMPT",
    "SKILL_KIND_PYTHON_TOOL",
    "AIAgentConfig",
    "AIAgentConfigCreate",
    "AIAgentConfigPublic",
    "AIAgentConfigUpdate",
    "AIAgentConfigsPublic",
    "AIAgentGrant",
    "AIAgentSkillLink",
    "AIAgentSyncItem",
    "AIAgentSyncRequest",
    "AIAgentSyncResponse",
    "AIAgentSyncResultItem",
    "AISkill",
    "AISkillCreate",
    "AISkillGrant",
    "AISkillPublic",
    "AISkillSyncItem",
    "AISkillSyncRequest",
    "AISkillSyncResponse",
    "AISkillSyncResultItem",
    "AISkillUpdate",
    "AISkillsPublic",
    "AgentActionAudit",
    "AgentRun",
    "CompanyLLMApiKeyCreate",
    "CompanyLLMApiKeyPublic",
    "CompanyLLMApiKeysPublic",
    "Message",
]

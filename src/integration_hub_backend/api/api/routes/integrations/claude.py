"""Claude / Anthropic integration — completions via smart-llm Agent.

API key lookup order (see AIService.complete for details):
  1. smart-llm DatabaseKeyStore — keyed by (company_id, provider)
  2. Legacy IntegrationCredential store — when credential_id is supplied
"""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from integration_hub_backend.api.api.deps import ApiKeyDep, SessionDep
from integration_hub_backend.api.services.ai_service import AIService

router = APIRouter(prefix="/claude", tags=["integrations"])


class ClaudeCompleteRequest(BaseModel):
    prompt: str
    system_prompt: str = "You are a helpful assistant. Respond in JSON."
    model_name: str = "claude-3-5-sonnet-20240620"
    provider: str = "anthropic"
    context: str | None = None
    # Optional legacy field — used if no key is registered in the key store
    credential_id: uuid.UUID | None = None


@router.post("/complete")
async def claude_complete(
    body: ClaudeCompleteRequest,
    db: SessionDep,
    api_key: ApiKeyDep,
) -> dict[str, Any]:
    """Run a completion using the smart-llm Agent.

    The LLM API key is resolved from smart-llm's DatabaseKeyStore first
    (registered via POST /api/v1/ai-agents/llm-keys/). If no key is found
    there, the legacy ``credential_id`` field can be used to look up an
    IntegrationCredential instead.
    """
    api_key.require_scope("integrations:claude")
    service = AIService(db)
    try:
        return await service.complete(
            company_id=api_key.company_id,
            prompt=body.prompt,
            system_prompt=body.system_prompt,
            model_name=body.model_name,
            provider=body.provider,
            context=body.context,
            credential_id=body.credential_id,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

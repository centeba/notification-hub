"""Phase G — CRUD endpoints for ``ai_agent_grants``.

Routes a ``scope='shared'`` agent's grant rows. Authorisation
rules:

- The owning ``company_admin`` (the tenant whose ``company_id``
  matches the agent's) can list / add / remove grants on agents
  they own.
- ``system_admin`` / ``platform_admin`` can manage grants for any
  agent.
- Non-owners cannot mutate grants on someone else's agent (returns
  403 even when they have a grant — the grant gives them access to
  RUN the agent, not to delegate that access further).

The grant ``pays`` field decides which tenant's LLM key bills calls
through the agent — see ``smart_llm.api.scoping.resolve_paying_company_id``.

The route file is small + additive: it doesn't change any existing
agent CRUD behaviour. Mounted via ``api_router.include_router`` in
``api/main.py``.
"""

import uuid
from datetime import datetime
from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from smart_llm.db.models import (
    SCOPE_SHARED,
    SHARED_PAYS_GRANTEE,
    SHARED_PAYS_OWNER,
)
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from integration_hub_backend.api.api.deps import (
    CompanyAdminDep,
    CurrentUserPayload,
    SessionDep,
)
from integration_hub_backend.api.models.ai_agent import (
    AIAgentConfig,
    AIAgentGrant,
)

router = APIRouter(prefix="/ai-agents", tags=["ai-agent-grants"])


class GrantPublic(BaseModel):
    agent_id: uuid.UUID
    grantee_company_id: uuid.UUID
    pays: Literal["owner", "grantee"]
    granted_by: uuid.UUID
    granted_at: datetime

    class Config:
        from_attributes = True


class GrantCreate(BaseModel):
    grantee_company_id: uuid.UUID
    pays: Literal["owner", "grantee"] = Field(
        default=SHARED_PAYS_OWNER,
        description=(
            "Which tenant's LLM key bills calls through this agent. "
            "'owner' = the agent's owning tenant pays; 'grantee' = "
            "the granted tenant pays (requires them to have their "
            "own LLM key registered)."
        ),
    )


async def _load_owned_agent(
    session: AsyncSession, agent_id: uuid.UUID, current_user: CurrentUserPayload
) -> AIAgentConfig:
    """Find ``agent_id`` AND verify ``current_user`` is allowed to
    manage grants on it. Returns the agent or raises 403/404."""
    agent = (
        (await session.execute(select(AIAgentConfig).where(AIAgentConfig.id == agent_id)))
        .scalars()
        .first()
    )
    if agent is None:
        raise HTTPException(status_code=404, detail="Agent not found")
    # Platform admins manage everything.
    if current_user.is_platform_admin:
        return agent
    # Otherwise the caller must own the agent.
    if agent.company_id is None or str(agent.company_id) != str(current_user.company_id):
        raise HTTPException(
            status_code=403,
            detail="Only the agent's owning company_admin can manage its grants.",
        )
    if agent.scope != SCOPE_SHARED:
        raise HTTPException(
            status_code=400,
            detail=f"Agent scope is {agent.scope!r} — grants only apply to scope='shared'.",
        )
    return agent


@router.get("/{agent_id}/grants", response_model=list[GrantPublic])
async def list_grants(
    agent_id: uuid.UUID,
    session: SessionDep,
    current_user: CompanyAdminDep,
) -> list[GrantPublic]:
    """List every grantee for ``agent_id``."""
    agent = await _load_owned_agent(session, agent_id, current_user)
    rows = (
        (await session.execute(select(AIAgentGrant).where(AIAgentGrant.agent_id == agent.id)))
        .scalars()
        .all()
    )
    return [GrantPublic.model_validate(r) for r in rows]


@router.post("/{agent_id}/grants", response_model=GrantPublic)
async def create_grant(
    agent_id: uuid.UUID,
    body: GrantCreate,
    session: SessionDep,
    current_user: CompanyAdminDep,
) -> GrantPublic:
    """Grant ``agent_id`` to ``body.grantee_company_id``. Re-issuing
    the same (agent, grantee) pair upserts the ``pays`` field rather
    than inserting a duplicate — idempotent shape that lets the UI
    flip 'pays' without a separate PATCH route."""
    agent = await _load_owned_agent(session, agent_id, current_user)

    if body.pays not in (SHARED_PAYS_OWNER, SHARED_PAYS_GRANTEE):
        raise HTTPException(
            status_code=422,
            detail=f"Invalid pays value {body.pays!r}",
        )

    # Upsert.
    existing = (
        (
            await session.execute(
                select(AIAgentGrant).where(
                    AIAgentGrant.agent_id == agent.id,
                    AIAgentGrant.grantee_company_id == body.grantee_company_id,
                )
            )
        )
        .scalars()
        .first()
    )
    if existing is not None:
        existing.pays = body.pays
        existing.granted_by = current_user.id
        await session.commit()
        await session.refresh(existing)
        return GrantPublic.model_validate(existing)

    row = AIAgentGrant(
        agent_id=agent.id,
        grantee_company_id=body.grantee_company_id,
        pays=body.pays,
        granted_by=current_user.id,
    )
    session.add(row)
    await session.commit()
    await session.refresh(row)
    return GrantPublic.model_validate(row)


@router.delete("/{agent_id}/grants/{grantee_company_id}", status_code=204)
async def delete_grant(
    agent_id: uuid.UUID,
    grantee_company_id: uuid.UUID,
    session: SessionDep,
    current_user: CompanyAdminDep,
) -> None:
    agent = await _load_owned_agent(session, agent_id, current_user)
    row = (
        (
            await session.execute(
                select(AIAgentGrant).where(
                    AIAgentGrant.agent_id == agent.id,
                    AIAgentGrant.grantee_company_id == grantee_company_id,
                )
            )
        )
        .scalars()
        .first()
    )
    if row is None:
        raise HTTPException(status_code=404, detail="Grant not found")
    await session.delete(row)
    await session.commit()
    return None

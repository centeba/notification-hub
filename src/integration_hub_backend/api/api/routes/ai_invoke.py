"""Run a configured AI agent by name, or a multi-agent graph.

Companion to the existing CRUD on ``/ai-agents``: this endpoint is the
inference entry point. The caller passes ``agent_name`` (the
``ai_agent_configs.name`` of an agent owned by their company) plus the
prompt; we resolve the agent config + its attached skills + LLM API key
and invoke ``smart_llm.Agent.run_with_skills``.

Auth: ``AnyAuthDep`` accepts either a user JWT or the raw
``INTERNAL_SERVICE_SECRET`` bearer (the latter is how vertical apps —
restoration-api, future cooling-tower-api, etc. — invoke platform
agents from their own backend via the SDK's ``SmartLlmInvokeClient``).

Why a separate prefix (``/ai-invoke``) instead of ``/ai-agents/run``:
the existing ``/ai-agents/{config_id}`` factory routes treat any path
segment after ``/ai-agents/`` as a config_id UUID. Mounting another
verb route under the same prefix would be order-sensitive and brittle
across factory + host-route boundaries. Distinct prefix keeps the two
concerns cleanly separated.
"""

import uuid
from datetime import UTC
from typing import Any

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field
from smart_llm.usage import BudgetExceededError

from integration_hub_backend.api.api.deps import AnyAuthDep, SessionDep
from integration_hub_backend.api.api.deps_ai_gate import assert_llm_allowed
from integration_hub_backend.api.services.ai_service import AIService

router = APIRouter(prefix="/ai-invoke", tags=["ai-invoke"])


class AgentRunRequest(BaseModel):
    agent_name: str | None = Field(
        None,
        description=(
            "Name of an AIAgentConfig owned by ``company_id``. The agent's "
            "configured provider, model, system_prompt, and attached skills "
            "drive the completion. Exactly one of ``agent_name`` or "
            "``agent_id`` must be supplied."
        ),
    )
    agent_id: uuid.UUID | None = Field(
        None,
        description=(
            "UUID of an AIAgentConfig row. Alternative to ``agent_name`` — "
            "workflow nodes store the UUID; human callers typically use the "
            "name. Exactly one of the two must be supplied."
        ),
    )
    prompt: str
    context: str | None = None
    company_id: uuid.UUID | None = Field(
        None,
        description=(
            "Tenant the agent runs against. Required when the caller is the "
            "internal service (no JWT-derived company); ignored when present "
            "from a JWT — JWT company always wins."
        ),
    )
    user_id: uuid.UUID | None = Field(
        None,
        description=(
            "The individual user whose action drove this call, recorded on the "
            "usage row for per-user billing attribution. Used only for "
            "internal-service callers (a vertical passing through its acting "
            "user); ignored for JWT callers — the JWT's user always wins."
        ),
    )


class AgentRunResponse(BaseModel):
    agent_name: str
    data: Any
    provider: str | None = None
    model: str | None = None


@router.post("/run", response_model=AgentRunResponse)
async def run_agent(
    body: AgentRunRequest,
    auth: AnyAuthDep,
    db: SessionDep,
) -> AgentRunResponse:
    """Invoke a named agent. Returns the LLM response + provider metadata.

    Skills attached to the agent are auto-resolved through
    ``Agent.run_with_skills`` — both ``kind=prompt`` (vertical-app YAML
    skills synced via SkillBundle, plus admin-authored prompt skills)
    and ``kind=python_tool`` (registered ActionTools).
    """
    # Resolve effective company_id. JWT → user.company_id;
    # internal-service → must be supplied in body.
    if auth.is_internal:
        if body.company_id is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="company_id is required for internal-service callers",
            )
        company_id = body.company_id
    else:
        if auth.user is None:
            # Defense; require_any_auth shouldn't reach here without raising
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Authentication required",
            )
        if auth.user.company_id is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="User has no company",
            )
        company_id = auth.user.company_id

    # Exactly one of agent_name / agent_id must be supplied.
    if body.agent_name is None and body.agent_id is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Exactly one of 'agent_name' or 'agent_id' must be provided",
        )
    if body.agent_name is not None and body.agent_id is not None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Provide either 'agent_name' or 'agent_id', not both",
        )

    # Phase F — tenant AI-budget gate. Fires the bell-icon alert + bus
    # publish on first cap trip, throttles on subsequent calls. Runs
    # before any LLM I/O so we don't spend a single token over cap.
    try:
        await assert_llm_allowed(db, company_id)
    except BudgetExceededError as exc:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="AI budget exhausted — contact your admin.",
        ) from exc

    # Attribute spend to the acting user: the JWT's user always wins; an
    # internal-service caller (a vertical) may pass the acting user in the body.
    effective_user_id = (
        auth.user.user_id if (not auth.is_internal and auth.user is not None) else body.user_id
    )

    service = AIService(db)
    try:
        result = await service.complete(
            company_id=company_id,
            prompt=body.prompt,
            context=body.context,
            agent_name=body.agent_name,
            agent_id=body.agent_id,
            user_id=effective_user_id,
        )
    except BudgetExceededError as exc:
        # Defense-in-depth: the inner Agent._check_budget tripped even
        # though the outer gate didn't. Map the same way as the gate.
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="AI budget exhausted — contact your admin.",
        ) from exc
    except ValueError as exc:
        # Common case: agent not found, or LLM key missing
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

    # get_db() only rolls back on exception — it never commits on success —
    # so without this the AIUsageEvent row(s) that Agent._record_usage()
    # flush()ed inside service.complete() are silently discarded when the
    # session closes, and month-to-date spend (assert_llm_allowed's cap
    # check) stays permanently $0 no matter how many real calls run.
    await db.commit()

    display_name = body.agent_name or str(body.agent_id)
    return AgentRunResponse(
        agent_name=display_name,
        data=result.get("data"),
        provider=result.get("provider"),
        model=result.get("model"),
    )


# ─── Autonomous-agent durable turn / dispatch (AgentRunWorkflow) ─────────────


def _resolve_company(auth: Any, body_company_id: uuid.UUID | None) -> uuid.UUID:
    if auth.is_internal:
        if body_company_id is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="company_id is required for internal-service callers",
            )
        return body_company_id
    if auth.user is None or auth.user.company_id is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="User has no company")
    company_id: uuid.UUID = auth.user.company_id
    return company_id


class AgentTurnRequest(BaseModel):
    agent_id: uuid.UUID
    messages: list[dict[str, Any]] = Field(default_factory=list)
    tool_results: list[dict[str, Any]] | None = None
    company_id: uuid.UUID | None = None
    acting_company_id: str | None = None


class AgentTurnResponse(BaseModel):
    status: str
    messages: list[dict[str, Any]]
    content: str | None = None
    tool_calls: list[dict[str, Any]] = Field(default_factory=list)
    usage: dict[str, Any] = Field(default_factory=dict)


@router.post("/agent-turn", response_model=AgentTurnResponse)
async def agent_turn(body: AgentTurnRequest, auth: AnyAuthDep, db: SessionDep) -> AgentTurnResponse:
    """Run ONE provider turn of an autonomous agent (durable workflow path)."""
    company_id = _resolve_company(auth, body.company_id)
    try:
        await assert_llm_allowed(db, company_id)
    except BudgetExceededError as exc:
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "AI budget exhausted.") from exc
    service = AIService(db)
    try:
        out = await service.agent_turn(
            company_id=company_id,
            agent_id=body.agent_id,
            messages=body.messages,
            tool_results=body.tool_results,
            acting_company_id=body.acting_company_id,
        )
    except ValueError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    # Same missing-commit gap as /run — see the comment there.
    await db.commit()
    return AgentTurnResponse(**out)


class AgentToolDispatchRequest(BaseModel):
    agent_id: uuid.UUID
    tool_call_id: str
    tool_name: str
    tool_input: dict[str, Any] = Field(default_factory=dict)
    company_id: uuid.UUID | None = None
    acting_company_id: str | None = None


@router.post("/agent-tool-dispatch")
async def agent_tool_dispatch(
    body: AgentToolDispatchRequest, auth: AnyAuthDep, db: SessionDep
) -> dict[str, Any]:
    """Execute ONE approved/allowed tool call for an autonomous run."""
    company_id = _resolve_company(auth, body.company_id)
    service = AIService(db)
    try:
        return await service.dispatch_tool(
            company_id=company_id,
            agent_id=body.agent_id,
            tool_call_id=body.tool_call_id,
            tool_name=body.tool_name,
            tool_input=body.tool_input,
            acting_company_id=body.acting_company_id,
        )
    except ValueError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc


class AgentRunStatusRequest(BaseModel):
    run_id: uuid.UUID
    agent_id: uuid.UUID
    acting_company_id: uuid.UUID
    status: str
    step_count: int = 0
    temporal_workflow_id: str | None = None


@router.get("/agent-runs")
async def list_agent_runs(
    auth: AnyAuthDep,
    db: SessionDep,
    status_filter: str | None = None,
    company_id: uuid.UUID | None = None,
) -> dict[str, Any]:
    """List autonomous runs for the caller's company (chassis Approvals
    surface uses ``status_filter=awaiting_approval``)."""
    from sqlalchemy import select as _select

    from integration_hub_backend.api.models.ai_agent import AgentRun

    cid = _resolve_company(auth, company_id)
    stmt = _select(AgentRun).where(AgentRun.acting_company_id == cid)
    if status_filter:
        stmt = stmt.where(AgentRun.status == status_filter)
    stmt = stmt.order_by(AgentRun.started_at.desc()).limit(100)
    rows = (await db.execute(stmt)).scalars().all()
    return {
        "data": [
            {
                "id": str(r.id),
                "agent_id": str(r.agent_id),
                "status": r.status,
                "step_count": r.step_count,
                "temporal_workflow_id": r.temporal_workflow_id,
                "started_at": r.started_at.isoformat() if r.started_at else None,
            }
            for r in rows
        ]
    }


@router.post("/agent-run-status")
async def agent_run_status(
    body: AgentRunStatusRequest, auth: AnyAuthDep, db: SessionDep
) -> dict[str, Any]:
    """Upsert the agent_runs ledger row for a durable autonomous run."""
    from datetime import datetime

    from integration_hub_backend.api.models.ai_agent import AgentRun

    row = await db.get(AgentRun, body.run_id)
    terminal = body.status in ("completed", "denied", "timeout", "failed")
    if row is None:
        row = AgentRun(
            id=body.run_id,
            agent_id=body.agent_id,
            acting_company_id=body.acting_company_id,
            status=body.status,
            step_count=body.step_count,
            temporal_workflow_id=body.temporal_workflow_id,
        )
        db.add(row)
    else:
        row.status = body.status
        row.step_count = body.step_count
        if body.temporal_workflow_id:
            row.temporal_workflow_id = body.temporal_workflow_id
    if terminal:
        row.ended_at = datetime.now(UTC)
    await db.commit()
    return {"ok": True}


# ─── Phase E2 — multi-agent graph dispatch ───────────────────────────────────


class AgentGraphRunRequest(BaseModel):
    spec: dict[str, Any] = Field(
        ...,
        description=(
            "`AgentGraphSpec` JSON: ``{entry, nodes: [{id, agent_id, "
            "next, branch}]}``. See ``smart_llm.orchestrator.AgentGraphSpec``. "
            "Cycles + depth > 3 raise 400 before any LLM call fires."
        ),
    )
    input: str = Field(..., description="Entry agent's user message. Forwarded verbatim.")
    context: str | None = None
    company_id: uuid.UUID | None = Field(
        None,
        description=(
            "Tenant for every agent in the graph. Same rules as ``/run`` — "
            "required for internal-service callers, ignored when a JWT "
            "supplies its own company_id."
        ),
    )


class AgentGraphRunResponse(BaseModel):
    results: dict[str, Any] = Field(
        ...,
        description=(
            "Mapping of graph-node-id → that agent's response data. "
            "Leaf consumers usually project a single leaf out of the map; "
            "intermediate nodes are included so callers can debug routing."
        ),
    )


@router.post("/run-graph", response_model=AgentGraphRunResponse)
async def run_agent_graph_endpoint(
    body: AgentGraphRunRequest,
    auth: AnyAuthDep,
    db: SessionDep,
) -> AgentGraphRunResponse:
    """Dispatch a multi-agent graph (Phase E2).

    The body's ``spec`` is parsed via ``AgentGraphSpec.from_dict``,
    which validates cycles + caps depth at ``MAX_DEPTH=3``. The
    orchestrator then walks the graph: each node calls
    :meth:`AIService.complete` (by ``agent_id``) and the response is
    handed downstream — fan-out parallel via ``asyncio.gather`` when
    a node has multiple ``next`` ids.

    Tenant resolution mirrors ``/run`` — JWT wins when present, else
    ``company_id`` is required in the body for internal-service
    callers (Mit Stack worker uses this path).
    """
    # Lazy import — keeps smart-llm a soft import boundary for the
    # endpoint module and matches the pattern used elsewhere.
    from smart_llm.orchestrator import AgentGraphSpec, run_agent_graph

    # Tenant resolution — identical to /run.
    if auth.is_internal:
        if body.company_id is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="company_id is required for internal-service callers",
            )
        company_id = body.company_id
    else:
        if auth.user is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Authentication required",
            )
        if auth.user.company_id is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="User has no company",
            )
        company_id = auth.user.company_id

    # Parse + validate spec. ValueError from cycle / depth / unknown
    # node references surfaces as a 400 so the caller can fix it
    # without burning LLM credits.
    try:
        spec = AgentGraphSpec.from_dict(body.spec)
    except (ValueError, KeyError, TypeError) as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid AgentGraphSpec: {exc}",
        ) from exc

    service = AIService(db)

    async def _runner(agent_id: str, input_text: str) -> dict[str, Any]:
        """Per-node dispatch — pulls the AIAgentConfig + skills via
        AIService.complete. ``context`` is shared across all nodes
        (top-level body field) so each agent sees the same upstream
        context if the caller supplied one."""
        result = await service.complete(
            company_id=company_id,
            prompt=input_text,
            context=body.context,
            agent_id=uuid.UUID(agent_id),
        )
        # The orchestrator branch-predicate evaluator inspects the
        # response payload directly — surface ``data`` so a leaf
        # agent producing ``{"intent": "summary"}`` matches a child
        # node's ``branch: "intent==summary"``.
        data = result.get("data")
        if isinstance(data, dict):
            return data
        return {"_text": data}

    try:
        out = await run_agent_graph(spec, body.input, runner=_runner)
    except ValueError as exc:
        # An orchestrator runtime error (missing node, branch
        # malformation) — still a client problem.
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc

    # Same missing-commit gap as /run — each graph node's usage row would
    # otherwise be discarded when the session closes. See the comment there.
    await db.commit()
    return AgentGraphRunResponse(results=out.get("results", {}))

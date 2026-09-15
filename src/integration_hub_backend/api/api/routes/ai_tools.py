"""Phase F1.5 — execute a registered ``ActionTool`` by name.

This is the HTTP entry point that lets workflow nodes (and any
future agent-driven dispatch) invoke a smart-llm action tool without
embedding the smart-llm runtime in every caller. The mit-stack
Temporal worker calls this endpoint from
``services/mit-stack/backend/temporal/activities/action_activity.py``.

Auth: ``CompanyAdminDep`` for human/UI invocation **or** the internal
service secret (``InternalServiceDep``) for sibling-service calls.
The route accepts whichever one resolves first; the second branch is
how mit-stack workers authenticate without a per-user JWT.

Why a router-factory wasn't used (unlike the agents/skills routers):
this endpoint is integration-hub-specific — it depends on
:mod:`smart_llm.builtins.integration_hub` which itself depends on
``integration_hub_backend``. There's no reusable factory shape.
"""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field, ValidationError

from integration_hub_backend.api.api.deps import (
    AnyAuthDep,
    SessionDep,
)

router = APIRouter(prefix="/ai-tools", tags=["ai-tools"])


class RunActionRequest(BaseModel):
    skill_name: str = Field(
        ...,
        description="Name of the tool registered in smart_llm.registry, e.g. 'postgres_run_query'.",
    )
    args: dict[str, Any] = Field(
        default_factory=dict,
        description="Tool-specific arguments matching the tool's args_model JSON schema.",
    )
    company_id: uuid.UUID | None = Field(
        None,
        description="Tenant the action runs against. Required when the "
        "caller is the internal service (no JWT-derived company); "
        "ignored when present from a CompanyAdmin JWT.",
    )


class RunActionResponse(BaseModel):
    skill_name: str
    result: dict[str, Any]


@router.post("/run", response_model=RunActionResponse)
async def run_action(
    body: RunActionRequest,
    session: SessionDep,
    auth: AnyAuthDep,
) -> RunActionResponse:
    """Validate ``body.skill_name`` against the registry, instantiate
    the tool, and dispatch. Returns whatever the tool's
    ``run_action`` produces, wrapped in a small envelope.

    Auth accepts either a user JWT (company_admin required for
    write-capable tools) or the raw ``INTERNAL_SERVICE_SECRET`` bearer
    string (used by the mit-stack Temporal worker for action_node
    dispatch).  Read-only tools (``ActionTool.read_only = True``) are
    accessible by any authenticated user — so non-admin members can
    view their own email inbox without an admin grant.
    """
    # Late imports keep the module importable on hosts that don't
    # bundle smart_llm.builtins.integration_hub (the import-guard in
    # that package logs and skips registration on those hosts).
    from smart_llm import builtins  # noqa: F401  — triggers self-registration
    from smart_llm.base import ActionTool
    from smart_llm.registry import get_tool_meta

    meta = get_tool_meta(body.skill_name)
    if meta is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Tool '{body.skill_name}' is not registered",
        )

    if not isinstance(meta.cls, type) or not issubclass(meta.cls, ActionTool):
        # Prompt-shaping Tools have no run_action; they're invoked by the
        # agent loop, not this endpoint.
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"Tool '{body.skill_name}' is not an ActionTool "
                f"(kind={meta.kind}). Only action tools can be invoked "
                f"directly via /ai-tools/run."
            ),
        )

    # ── Permission check ──────────────────────────────────────────────────────
    # Internal-service callers (Temporal worker) bypass user-level checks.
    # For JWT callers, read-only tools are accessible to any logged-in user;
    # write-capable tools require company_admin.
    tool_read_only: bool = getattr(meta.cls, "read_only", False)

    if auth.is_internal:
        # Worker path — company comes from the request body.
        effective_company_id = body.company_id
    elif auth.user is None:
        # Shouldn't happen (is_internal=False means JWT path), but guard.
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required"
        )
    elif tool_read_only or auth.user.is_company_admin:
        effective_company_id = auth.user.company_id or body.company_id
    else:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Company admin required for non-read-only tools",
        )

    args_cls = getattr(meta.cls, "args_model", None)
    if args_cls is None:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Tool '{body.skill_name}' has no args_model",
        )

    try:
        # Force the effective company_id into args when the tool's args_model
        # declares a company_id field. This is the tenant-isolation boundary:
        # the value MUST come from the authenticated caller (JWT), never from
        # attacker-controllable ``body.args``. A previous ``setdefault`` let a
        # caller-supplied foreign company_id survive — a cross-tenant read hole
        # (SEC C1). Overwrite unconditionally so the trusted value always wins.
        args_dict = dict(body.args)
        if effective_company_id is not None and "company_id" in (args_cls.model_fields or {}):
            args_dict["company_id"] = effective_company_id
        validated = args_cls(**args_dict)
    except ValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"args_validation_error": exc.errors()},
        ) from exc

    instance = meta.cls()
    try:
        result = await instance.run_action(validated, db_session=session)
    except HTTPException:
        raise
    except Exception as exc:  # pragma: no cover — surfaced as 500
        # Tools that wrap external APIs may raise their own typed
        # errors; we round-trip them as 502 with the message so the
        # caller can decide whether to retry.
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Tool '{body.skill_name}' failed: {exc}",
        ) from exc

    if not isinstance(result, dict):
        result = {"result": result}

    return RunActionResponse(skill_name=body.skill_name, result=result)

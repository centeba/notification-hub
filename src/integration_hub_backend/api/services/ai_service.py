"""AI service — completions via the smart-llm agent registry (Phase D).

Pre-Phase-D this module instantiated :class:`smart_llm.Agent` directly.
Now it routes every request through an :class:`AIAgentConfig`:

- If the caller passes ``agent_name``, that named agent runs against
  this company. Its ``provider_type`` / ``model_name`` /
  ``system_prompt`` / attached skills override the generic args below.
- Otherwise the legacy generic-completion path runs: a transient
  ``AIAgentConfig``-equivalent agent is built from the explicit
  ``provider`` + ``model_name`` args. Skills default to ``[]``.

In both branches the API key is resolved via smart-llm's
``DatabaseKeyStore`` (with a legacy ``credential_id`` fallback for
older callers), so nothing constructs ``Agent`` outside of this layer.
"""

import json
import uuid
from typing import Any

from smart_llm import Agent, builtins  # noqa: F401 — registers builtin skills
from smart_llm.api.llm_service import get_company_api_key
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from integration_hub_backend.api.crud.integration_credentials import (
    get_credential,
    get_decrypted,
)
from integration_hub_backend.api.models.ai_agent import (
    AgentActionAudit,
    AIAgentConfig,
    AIAgentSkillLink,
    AISkill,
)
from integration_hub_backend.api.models.ai_usage import AIUsageEvent
from integration_hub_backend.api.models.company_settings import (
    NotificationCompanySettings as _CompanySettings,
)


class AIService:
    def __init__(self, db: AsyncSession):
        self.db = db

    # ── public API ──────────────────────────────────────────────────────────

    async def complete(
        self,
        company_id: uuid.UUID,
        prompt: str,
        system_prompt: str = "You are a helpful assistant. Respond in JSON.",
        model_name: str = "claude-3-5-sonnet-20240620",
        provider: str = "anthropic",
        context: str | None = None,
        # Legacy: resolved via integration_credentials table when provided.
        credential_id: uuid.UUID | None = None,
        # Phase D: name of an AIAgentConfig owned by ``company_id``. When
        # supplied, the agent's provider/model/system_prompt/skills win
        # and the explicit args above are ignored. Required signature
        # stays the same for backward compatibility with callers that
        # don't yet know about agents.
        agent_name: str | None = None,
        # Phase B: UUID alternative to agent_name. Workflow nodes store
        # the config ID; callers may pass either field.
        agent_id: uuid.UUID | None = None,
        # Platform metering (this plan): the individual user whose action drove
        # the call, recorded on the usage row for per-user billing attribution.
        # None for system/cron-triggered runs.
        user_id: uuid.UUID | None = None,
    ) -> dict[str, Any]:
        cfg, skill_names, skill_ids = await self._resolve_agent_config(
            company_id, agent_name=agent_name, agent_id=agent_id
        )
        # Attribute spend to a single skill when the agent runs exactly one
        # (the common domain-skill case); multi-skill agents attribute to the
        # agent only (agent_id), since no one skill owns the call.
        primary_skill_id = str(skill_ids[0]) if len(skill_ids) == 1 else None

        if cfg is not None:
            provider = cfg.provider_type
            model_name = cfg.model_name or model_name
            system_prompt = cfg.system_prompt or system_prompt

        api_key = await self._resolve_api_key(company_id, provider, credential_id)

        # Phase E4 — load the tenant's monthly AI budget so the Agent can
        # enforce ``assert_within_budget`` before each provider call and
        # ``record_usage`` after it. Missing row → 0.0 (no cap).
        monthly_budget = await self._load_monthly_budget(company_id)
        company_pii, pii_categories = await self._load_company_pii(company_id)
        pii_policy, pii_allow_vision, pii_firewall = self._resolve_pii(
            company_pii, pii_categories, cfg
        )

        agent = Agent(
            name=cfg.name if cfg else f"integration-hub-{company_id}",
            provider_type=provider,
            system_prompt=system_prompt,
            api_key=api_key,
            model_name=model_name,
            usage_session=self.db,
            usage_model=AIUsageEvent,
            company_id=str(company_id),
            agent_id=str(cfg.id) if cfg else None,
            user_id=str(user_id) if user_id else None,
            skill_id=primary_skill_id,
            monthly_budget_usd=monthly_budget,
            pii_policy=pii_policy,
            pii_firewall=pii_firewall,
            pii_allow_vision=pii_allow_vision,
        )
        if skill_names:
            # Reuse the same session for the prompt-skill DB lookup path.
            setattr(self.db, "_smart_llm_ai_skill_cls", AISkill)
            # M3 — wire the per-agent caps that were schema-only: max_steps caps
            # the tool-loop rounds; max_cost_usd caps the per-run spend.
            run_kwargs: dict[str, Any] = {}
            if cfg is not None and cfg.max_steps:
                run_kwargs["max_iterations"] = int(cfg.max_steps)
            if cfg is not None and cfg.max_cost_usd:
                from smart_llm import LoopGuards

                run_kwargs["guards"] = LoopGuards(max_cost_usd=float(cfg.max_cost_usd))
            # Deny-by-default tool gating on the standard (non-autonomous) path
            # too: if this agent binds any ActionTool, every call goes through
            # the ToolPolicyGate (risk × approval_mode, cross-tenant authz,
            # audited) — closing the gap where the invoke path ran ActionTools
            # ungated. No cross-company delegation here, so acting == company.
            if cfg is not None:
                gate = await self._build_policy_gate(cfg, str(company_id))
                if gate is not None:
                    run_kwargs["policy_gate"] = gate
            response = await agent.run_with_skills(
                prompt,
                skill_names,
                db_session=self.db,
                context=context,
                **run_kwargs,
            )
        else:
            response = await agent.analyze(input_text=prompt, context=context)
        return {
            "data": response.data,
            "provider": response.provider,
            "model": response.metadata.get("model"),
        }

    async def _build_policy_gate(self, cfg: AIAgentConfig, acting_company_id: str) -> Any:
        """Build a deny-by-default ``ToolPolicyGate`` for one agent run.

        The gate is the agent's per-tool ``approval_mode`` map + a cross-company
        authz delegation checker + an audit sink. Used on BOTH the autonomous
        path and the **standard invoke path** (``complete``) so that every
        ``ActionTool`` call is gated — not only autonomous runs. Previously the
        non-autonomous path ran attached ActionTools with no gate (only the
        content-safety guard + budget), so a write/external tool could dispatch
        unattended. Returns ``None`` when the agent has no tool bindings (a
        pure prompt agent needs no gate).
        """
        from smart_llm.security.tool_policy import AgentRunContext, ToolPolicyGate

        rows = await self.db.execute(
            select(AISkill.name, AIAgentSkillLink.approval_mode)
            .join(AIAgentSkillLink, AIAgentSkillLink.skill_id == AISkill.id)
            .where(AIAgentSkillLink.agent_config_id == cfg.id)
            .where(AISkill.is_active.is_(True))
        )
        tool_modes = {name: mode for name, mode in rows.all()}
        if not tool_modes:
            return None

        async def _authz_checker(aid: str, target_company: str, action: str) -> bool:
            try:
                from integration_hub_backend._platform.authz import authz_check

                allowed: bool = await authz_check(
                    f"company:{target_company}#member",
                    "delegate",
                    f"agent:{aid}",
                    context={"action": action},
                    fail_closed=True,
                )
                return allowed
            except Exception:  # noqa: BLE001 — authz unreachable → deny
                return False

        async def _audit_sink(audit: dict[str, Any]) -> None:
            self.db.add(
                AgentActionAudit(
                    agent_run_id=None,
                    agent_id=cfg.id,
                    tool_name=audit.get("tool_name", ""),
                    acting_company_id=uuid.UUID(acting_company_id),
                    target_company_id=(
                        uuid.UUID(audit["target_company_id"])
                        if audit.get("target_company_id")
                        else None
                    ),
                    decision=audit.get("decision", ""),
                    reason=(audit.get("reason") or "")[:255],
                    args_digest=audit.get("args_digest"),
                )
            )
            await self.db.commit()

        ctx = AgentRunContext(
            agent_id=str(cfg.id),
            acting_company_id=acting_company_id,
            tool_modes=tool_modes,
            authz_checker=_authz_checker,
            audit_sink=_audit_sink,
        )
        return ToolPolicyGate(ctx)

    # ── Autonomous run path (durable AgentRunWorkflow) ───────────────────────

    async def _build_provider_tools_gate(
        self,
        company_id: uuid.UUID,
        agent_id: uuid.UUID,
        acting_company_id: str,
    ) -> tuple[Any, Any, Any, AIAgentConfig]:
        """Build the (provider, action_tools, gate, cfg) tuple for one
        autonomous turn. The policy gate is wired with the agent's per-tool
        ``approval_mode`` map + a cross-company authz delegation checker."""
        from smart_llm.autonomous import resolve_action_tools
        from smart_llm.security.tool_policy import AgentRunContext, ToolPolicyGate

        cfg = await self.db.get(AIAgentConfig, agent_id)
        if cfg is None or cfg.company_id != company_id:
            raise ValueError(f"AIAgentConfig {agent_id} not found for company {company_id}")

        # skill name → approval_mode (the per-tool allow-list + policy)
        rows = await self.db.execute(
            select(AISkill.name, AIAgentSkillLink.approval_mode)
            .join(AIAgentSkillLink, AIAgentSkillLink.skill_id == AISkill.id)
            .where(AIAgentSkillLink.agent_config_id == cfg.id)
            .where(AISkill.is_active.is_(True))
        )
        tool_modes = {name: mode for name, mode in rows.all()}

        api_key = await self._resolve_api_key(company_id, cfg.provider_type, None)
        monthly_budget = await self._load_monthly_budget(company_id)
        company_pii, pii_categories = await self._load_company_pii(company_id)
        pii_policy, pii_allow_vision, pii_firewall = self._resolve_pii(
            company_pii, pii_categories, cfg
        )
        agent = Agent(
            name=cfg.name,
            provider_type=cfg.provider_type,
            system_prompt=cfg.system_prompt or "You are an autonomous assistant.",
            api_key=api_key,
            model_name=cfg.model_name,
            usage_session=self.db,
            usage_model=AIUsageEvent,
            company_id=str(company_id),
            agent_id=str(cfg.id),
            monthly_budget_usd=monthly_budget,
            pii_policy=pii_policy,
            pii_firewall=pii_firewall,
            pii_allow_vision=pii_allow_vision,
        )
        setattr(self.db, "_smart_llm_ai_skill_cls", AISkill)
        action_tools = await resolve_action_tools(
            list(tool_modes.keys()), self.db, ai_skill_cls=AISkill
        )

        async def _authz_checker(aid: str, target_company: str, action: str) -> bool:
            try:
                from integration_hub_backend._platform.authz import authz_check

                allowed: bool = await authz_check(
                    f"company:{target_company}#member",
                    "delegate",
                    f"agent:{aid}",
                    context={"action": action},
                    fail_closed=True,
                )
                return allowed
            except Exception:  # noqa: BLE001 — authz unreachable → deny
                return False

        async def _audit_sink(audit: dict[str, Any]) -> None:
            self.db.add(
                AgentActionAudit(
                    agent_run_id=None,
                    agent_id=cfg.id,
                    tool_name=audit.get("tool_name", ""),
                    acting_company_id=uuid.UUID(acting_company_id),
                    target_company_id=(
                        uuid.UUID(audit["target_company_id"])
                        if audit.get("target_company_id")
                        else None
                    ),
                    decision=audit.get("decision", ""),
                    reason=(audit.get("reason") or "")[:255],
                    args_digest=audit.get("args_digest"),
                )
            )
            await self.db.commit()

        ctx = AgentRunContext(
            agent_id=str(cfg.id),
            acting_company_id=acting_company_id,
            tool_modes=tool_modes,
            authz_checker=_authz_checker,
            audit_sink=_audit_sink,
        )
        return agent, action_tools, ToolPolicyGate(ctx), cfg

    async def agent_turn(
        self,
        company_id: uuid.UUID,
        agent_id: uuid.UUID,
        messages: list[dict[str, Any]],
        tool_results: list[dict[str, Any]] | None = None,
        acting_company_id: str | None = None,
    ) -> dict[str, Any]:
        """Run exactly one provider turn of an autonomous agent. The Temporal
        AgentRunWorkflow owns the ``messages`` array (opaque, provider-shaped)
        and the approval orchestration; this just advances one step + evaluates
        the policy gate for any requested tool calls."""
        from smart_llm.agent_loop import build_tool_results_message, run_one_turn

        acting = acting_company_id or str(company_id)
        agent, action_tools, gate, cfg = await self._build_provider_tools_gate(
            company_id, agent_id, acting
        )
        msgs = list(messages)
        if tool_results:
            shaped = build_tool_results_message(tool_results, agent._provider)
            if isinstance(shaped, list):
                msgs.extend(shaped)
            else:
                msgs.append(shaped)
        out = await run_one_turn(
            agent._provider, agent.system_prompt, msgs, action_tools, policy_gate=gate
        )
        usage = out.get("usage", {})
        if out["status"] == "final":
            return {"status": "final", "content": out["content"], "messages": msgs, "usage": usage}
        msgs.append(out["assistant_message"])
        return {
            "status": "tool_calls",
            "messages": msgs,
            "tool_calls": out["tool_calls"],
            "usage": usage,
        }

    async def dispatch_tool(
        self,
        company_id: uuid.UUID,
        agent_id: uuid.UUID,
        tool_call_id: str,
        tool_name: str,
        tool_input: dict[str, Any],
        acting_company_id: str | None = None,
    ) -> dict[str, Any]:
        """Execute ONE approved/allowed tool call and return its raw result dict
        ({tool_call_id, name, content}) for the workflow to feed into the next turn."""
        import json as _json

        acting = acting_company_id or str(company_id)
        _, action_tools, _, _ = await self._build_provider_tools_gate(company_id, agent_id, acting)
        by_name = {}
        for t in action_tools:
            by_name[type(t).__name__] = t
            rn = getattr(t, "_registry_name", None)
            if rn:
                by_name[rn] = t
        tool = by_name.get(tool_name)
        if tool is None:
            content = _json.dumps({"error": f"unknown tool {tool_name!r}"})
        else:
            try:
                # Tenant-isolation boundary (SEC C1): the model authored
                # ``tool_input``; it must NOT be trusted to set company_id. For
                # any tool whose args declare company_id, force the acting
                # tenant's id so a tenant-scoped tool (e.g. postgres_run_query)
                # can never be steered — by prompt injection or otherwise — to
                # omit the scope or target a foreign tenant.
                ti = dict(tool_input or {})
                args_model: Any = getattr(tool, "args_model", None)
                if args_model is not None and "company_id" in (
                    getattr(args_model, "model_fields", {}) or {}
                ):
                    ti["company_id"] = acting
                args = args_model(**ti)
                result = await tool.run_action(args, db_session=self.db)
                content = _json.dumps(result, default=str)
            except Exception as exc:  # noqa: BLE001
                content = _json.dumps({"error": str(exc)})
        return {"tool_call_id": tool_call_id, "name": tool_name, "content": content}

    # ── helpers ─────────────────────────────────────────────────────────────

    async def _resolve_agent_config(
        self,
        company_id: uuid.UUID,
        agent_name: str | None = None,
        agent_id: uuid.UUID | None = None,
    ) -> tuple[AIAgentConfig | None, list[str], list[uuid.UUID]]:
        if agent_id is not None:
            # Phase B: lookup by UUID (workflow nodes store the ID)
            cfg = await self.db.get(AIAgentConfig, agent_id)
            if cfg is None or cfg.company_id != company_id:
                raise ValueError(f"AIAgentConfig {agent_id} not found for company {company_id}")
            if not cfg.is_active:
                raise ValueError(f"AIAgentConfig {agent_id} is inactive")
        elif agent_name:
            cfg = (
                await self.db.execute(
                    select(AIAgentConfig)
                    .where(
                        AIAgentConfig.company_id == company_id,
                        AIAgentConfig.name == agent_name,
                        AIAgentConfig.is_active.is_(True),
                    )
                    .limit(1)
                )
            ).scalar_one_or_none()
            if cfg is None:
                raise ValueError(f"AIAgentConfig '{agent_name}' not found for company {company_id}")
        else:
            return None, [], []
        skill_rows = await self.db.execute(
            select(AISkill.name, AISkill.id)
            .join(AIAgentSkillLink, AIAgentSkillLink.skill_id == AISkill.id)
            .where(AIAgentSkillLink.agent_config_id == cfg.id)
            .where(AISkill.is_active.is_(True))
        )
        rows = skill_rows.all()
        return cfg, [r[0] for r in rows], [r[1] for r in rows]

    async def _load_monthly_budget(self, company_id: uuid.UUID) -> float:
        """Read ``monthly_ai_budget_usd`` from ``company_settings``.

        Returns 0.0 (no cap) when the row is missing — keeps the
        migration backwards-compatible for tenants who haven't updated
        settings.
        """
        stmt = select(_CompanySettings).where(_CompanySettings.company_id == str(company_id))
        row = (await self.db.execute(stmt)).scalars().first()
        return float(getattr(row, "monthly_ai_budget_usd", 0.0) or 0.0) if row else 0.0

    async def _load_company_pii(self, company_id: uuid.UUID) -> tuple[str | None, list[str] | None]:
        """Read the company's PII masking policy + category allowlist.

        Returns ``(policy, categories)`` where a ``None`` policy means the
        company hasn't set one — the firewall then falls back to the env default
        ('enforce'), so masking is on out-of-the-box.
        """
        stmt = select(_CompanySettings).where(_CompanySettings.company_id == str(company_id))
        row = (await self.db.execute(stmt)).scalars().first()
        if row is None:
            return None, None
        return getattr(row, "pii_masking_policy", None), getattr(row, "pii_categories", None)

    def _resolve_pii(
        self, company_policy: str | None, categories: list[str] | None, cfg: Any
    ) -> tuple[str, bool, Any]:
        """Effective policy + vision escape hatch + a category-scoped firewall.

        Combines the company policy with the agent's per-agent
        ``model_configuration`` override (an agent may only tighten). Returns
        ``(policy, allow_vision_pii, firewall)`` — ``firewall`` is ``None`` when
        no category restriction applies, letting the Agent build its default.
        """
        from smart_llm.pii import PiiFirewall, resolve_pii_policy

        model_cfg: dict[str, Any] = {}
        raw = getattr(cfg, "model_configuration", None) if cfg is not None else None
        if raw:
            try:
                model_cfg = json.loads(raw) or {}
            except (json.JSONDecodeError, TypeError):
                model_cfg = {}
        policy = resolve_pii_policy(company_policy, model_cfg)
        allow_vision = bool(model_cfg.get("allow_vision_pii", False))
        firewall = PiiFirewall(categories=list(categories)) if categories else None
        return policy, allow_vision, firewall

    async def _resolve_api_key(
        self,
        company_id: uuid.UUID,
        provider: str,
        credential_id: uuid.UUID | None,
    ) -> str:
        api_key: str | None = None
        try:
            api_key = await get_company_api_key(self.db, company_id, provider)
        except Exception:
            # Key store may not be initialised yet during testing.
            pass
        if not api_key and credential_id is not None:
            cred = await get_credential(self.db, credential_id, company_id)
            if not cred:
                raise ValueError("Credential not found")
            api_key = get_decrypted(cred).get("api_key", "")
        if not api_key:
            raise ValueError(
                f"No LLM API key found for provider '{provider}'. "
                "Register one via POST /api/v1/ai-agents/llm-keys/."
            )
        return api_key

"""API router aggregation."""

from fastapi import APIRouter
from smart_llm.api.llm_service import get_key_store

# ── smart-llm router factories ────────────────────────────────────────────────
from smart_llm.api.routers.agents import create_agents_router
from smart_llm.api.routers.skills import create_skills_router
from smart_llm.api.routers.streaming import create_streaming_router
from smart_llm.api.routers.usage import create_usage_router
from sqlalchemy.ext.asyncio import AsyncSession

from integration_hub_backend.api.api.deps import (
    CompanyAdminDep,
    CurrentUser,
    InternalServiceDep,
    PlatformAdminDep,
    SessionDep,
)
from integration_hub_backend.api.api.routes import (
    ai_agent_grants,
    ai_invoke,
    ai_search,
    ai_tools,
    api_keys,
    channels,
    company_settings,
    connectors,
    device_tokens,
    event_types,
    events,
    integration_credentials,
    integrations_catalog,
    logs,
    metrics,
    oauth_connect,
    packs,
    platform_llm_keys,
    preferences,
    rules,
    subscription_bus,
    templates,
    webhooks,
)
from integration_hub_backend.api.api.routes.admin import gdpr as gdpr_admin
from integration_hub_backend.api.api.routes.admin import internal_seed as internal_seed_admin
from integration_hub_backend.api.api.routes.admin import observability as observability_admin

# Scraper sessions are owned by mit-stack — its alembic migration
# creates ``scraper_sessions`` with ``org_id`` (FK to organizations).
# This service previously had a copy-pasted ``ScraperSession`` model
# that declared ``company_id`` and 500'd every read with
# ``UndefinedColumnError``. The duplicate route, model, service,
# Temporal activity, and Temporal workflow are no longer wired here.
# The orphaned files in routes/scraper.py, models/scraper.py,
# services/scraper_service.py, temporal/activities/scraper_activity.py
# and temporal/workflows/scraper_workflows.py can be deleted; nothing
# imports them anymore. The canonical surface is mit-stack's
# ``GET /api/v1/scraper/sessions``.
from integration_hub_backend.api.api.routes.integrations import (
    claude,
    datadog,
    elasticsearch,
    excel,
    gmail,
    google_drive,
    google_sheets,
    grafana,
    kibana,
    mailchimp,
    outlook,
    s3,
    splunk,
    stripe,
)
from integration_hub_backend.api.core.audit import log_audit
from integration_hub_backend.api.core.config import settings
from integration_hub_backend.api.models.ai_agent import (
    AIAgentConfig,
    AIAgentConfigCreate,
    AIAgentConfigPublic,
    AIAgentConfigsPublic,
    AIAgentConfigUpdate,
    AIAgentGrant,
    AIAgentSkillLink,
    AIAgentSyncRequest,
    AIAgentSyncResponse,
    AIAgentSyncResultItem,
    AISkill,
    AISkillCreate,
    AISkillGrant,
    AISkillPublic,
    AISkillsPublic,
    AISkillSyncRequest,
    AISkillSyncResponse,
    AISkillSyncResultItem,
    AISkillUpdate,
    CompanyLLMApiKeyCreate,
    CompanyLLMApiKeyPublic,
    CompanyLLMApiKeysPublic,
    Message,
)

api_router = APIRouter()

# ── Notification routes ────────────────────────────────────────────────────────
api_router.include_router(events.router)
api_router.include_router(event_types.router)
api_router.include_router(rules.router)
# Inbound connector ingestion (claims-platform A4) — generic FNOL gateway.
api_router.include_router(connectors.router)
# Push device-token registration (A8).
api_router.include_router(device_tokens.router)
# Scorecard / analytics metrics (A6).
api_router.include_router(metrics.router)

# Phase 5.1 — generic WebSocket subscription bus. See
# routes/subscription_bus.py for the topic ↔ Redis-channel mapping
# table and the wire protocol (token-in-first-message).
api_router.include_router(subscription_bus.router)
api_router.include_router(templates.router)
api_router.include_router(preferences.router)
api_router.include_router(channels.router)
api_router.include_router(logs.router)
api_router.include_router(api_keys.router)
api_router.include_router(webhooks.router)
api_router.include_router(company_settings.router)

# ── Integration Hub routes ─────────────────────────────────────────────────────
api_router.include_router(integration_credentials.router)
api_router.include_router(oauth_connect.router)
# JWT-readable connector catalog (GET /api/v1/integrations) — what the
# chassis Integration Hub "Integrations" tab lists. Registered before the
# per-connector action routers; the bare ``/integrations`` GET doesn't
# collide with ``/integrations/<connector>/...``.
api_router.include_router(integrations_catalog.router)
api_router.include_router(gmail.router, prefix="/integrations")
api_router.include_router(outlook.router, prefix="/integrations")
api_router.include_router(stripe.router, prefix="/integrations")
api_router.include_router(s3.router, prefix="/integrations")
api_router.include_router(google_drive.router, prefix="/integrations")
api_router.include_router(google_sheets.router, prefix="/integrations")
api_router.include_router(mailchimp.router, prefix="/integrations")
api_router.include_router(excel.router, prefix="/integrations")
api_router.include_router(datadog.router, prefix="/integrations")
api_router.include_router(splunk.router, prefix="/integrations")
api_router.include_router(grafana.router, prefix="/integrations")
api_router.include_router(elasticsearch.router, prefix="/integrations")
api_router.include_router(kibana.router, prefix="/integrations")
api_router.include_router(claude.router, prefix="/integrations")
api_router.include_router(observability_admin.router)
api_router.include_router(internal_seed_admin.router)
api_router.include_router(gdpr_admin.router)
# scraper.router removed — see comment on the routes-import block above.
api_router.include_router(ai_tools.router)
api_router.include_router(ai_search.router)
api_router.include_router(ai_invoke.router)
# Phase G — cross-tenant grants + platform-level LLM keys.
api_router.include_router(ai_agent_grants.router)
api_router.include_router(platform_llm_keys.router)
# Phase 1B — pack discovery + uninstall HTTP surface.
api_router.include_router(packs.router)

# ── smart-llm AI agent & skill management routes ──────────────────────────────
_agents_router = create_agents_router(
    SessionDep=SessionDep,
    CurrentUser=CurrentUser,
    CompanyAdminDep=CompanyAdminDep,
    # Authoring (create/update/delete agent, add/remove LLM key) is platform-
    # admin only — tenants are consumers, not authors.
    PlatformAdminDep=PlatformAdminDep,
    # Per-deployment domain isolation: only ingest THIS domain's agents.
    expected_source_app=settings.APP_SOURCE or None,
    AIAgentConfig=AIAgentConfig,
    AISkill=AISkill,
    AISkillPublic=AISkillPublic,
    AIAgentSkillLink=AIAgentSkillLink,
    AIAgentConfigPublic=AIAgentConfigPublic,
    AIAgentConfigCreate=AIAgentConfigCreate,
    AIAgentConfigUpdate=AIAgentConfigUpdate,
    AIAgentConfigsPublic=AIAgentConfigsPublic,
    CompanyLLMApiKeyPublic=CompanyLLMApiKeyPublic,
    CompanyLLMApiKeyCreate=CompanyLLMApiKeyCreate,
    CompanyLLMApiKeysPublic=CompanyLLMApiKeysPublic,
    Message=Message,
    log_audit=log_audit,
    get_key_store=get_key_store,
    # Sync endpoint (vertical apps post their YAML agent configs here at startup)
    InternalServiceDep=InternalServiceDep,
    AIAgentSyncRequest=AIAgentSyncRequest,
    AIAgentSyncResponse=AIAgentSyncResponse,
    AIAgentSyncResultItem=AIAgentSyncResultItem,
    # Phase G — grant model widens list/get to platform + granted-shared rows.
    AIAgentGrant=AIAgentGrant,
)

_skills_router = create_skills_router(
    SessionDep=SessionDep,
    CurrentUser=CurrentUser,
    CompanyAdminDep=CompanyAdminDep,
    # Authoring (create/update/delete skill) is platform-admin only.
    PlatformAdminDep=PlatformAdminDep,
    # Per-deployment domain isolation: only ingest THIS domain's skills.
    expected_source_app=settings.APP_SOURCE or None,
    AISkill=AISkill,
    AISkillPublic=AISkillPublic,
    AISkillCreate=AISkillCreate,
    AISkillUpdate=AISkillUpdate,
    AISkillsPublic=AISkillsPublic,
    Message=Message,
    log_audit=log_audit,
    # Sync endpoint (vertical apps post their YAML skills here at startup)
    InternalServiceDep=InternalServiceDep,
    AISkillSyncRequest=AISkillSyncRequest,
    AISkillSyncResponse=AISkillSyncResponse,
    AISkillSyncResultItem=AISkillSyncResultItem,
    # Phase G — wire the grant model so the lookup widens to
    # platform/shared visibility.
    AISkillGrant=AISkillGrant,
)

api_router.include_router(_agents_router)
api_router.include_router(_skills_router)


# ── Phase E3: WebSocket streaming proxy ──────────────────────────────────────
# The JWT decoder used by every WS route now lives in `ws_auth.py` so
# the Phase 5.1 subscription bus can reuse it. Keep this thin shim for
# any in-module references that still call `_resolve_token_for_stream`.
from integration_hub_backend.api.api.ws_auth import (
    resolve_token_for_stream as _resolve_token_for_stream,  # noqa: F401
)


async def _resolve_key_for_stream(config: AIAgentConfig, company_id: str) -> str | None:
    """Return the decrypted API key for the agent's company.

    Reuses the same singleton :class:`DatabaseKeyStore` that the REST
    routes use — keeps key rotation/auditing in one place.
    """
    import uuid as _uuid

    store = get_key_store()
    keys = await store.load_keys(config.provider_type, scope_id=_uuid.UUID(str(company_id)))
    return keys[0] if keys else None


from integration_hub_backend.api.core.db import AsyncSessionLocal as _AsyncSessionLocal


# ── Phase E4 — usage + budget loaders ────────────────────────────────────
async def _load_company_budget(session: AsyncSession, company_id: str) -> float:
    """Read ``monthly_ai_budget_usd`` from ``company_settings``.

    Returns 0.0 (no cap) when no settings row exists for the tenant.
    The column is a real mapped attribute on the ORM (migration 015);
    read it directly rather than via ``getattr(..., default)`` so a
    future rename surfaces as an AttributeError instead of silently
    returning 0 — that ``getattr`` default is exactly what hid the
    original save-doesn't-persist bug for months.
    """
    from sqlalchemy import select as _select

    from integration_hub_backend.api.models.company_settings import (
        NotificationCompanySettings as CompanySettings,
    )

    stmt = _select(CompanySettings).where(CompanySettings.company_id == company_id)
    row = (await session.execute(stmt)).scalars().first()
    if row is None:
        return 0.0
    return float(row.monthly_ai_budget_usd or 0.0)


async def _set_company_budget(session: AsyncSession, company_id: str, value: float) -> None:
    from sqlalchemy import select as _select

    from integration_hub_backend.api.models.company_settings import (
        NotificationCompanySettings as CompanySettings,
    )

    stmt = _select(CompanySettings).where(CompanySettings.company_id == company_id)
    row = (await session.execute(stmt)).scalars().first()
    if row is None:
        row = CompanySettings(company_id=company_id, monthly_ai_budget_usd=value)
        session.add(row)
    else:
        row.monthly_ai_budget_usd = value


# Phase F — the cross-service ``/ai-usage/assert-allowed`` endpoint
# needs the internal-service auth dep, the NotificationDeliveryLog
# model (for bell-icon alert insert), and a Redis client factory (for
# throttle + bus publish). Wired here so the smart_llm router stays
# host-agnostic.
from integration_hub_backend.api.api.deps import InternalServiceDep
from integration_hub_backend.api.core.redis import get_redis_pool as _get_redis_pool
from integration_hub_backend.api.models.ai_usage import AIUsageEvent
from integration_hub_backend.api.models.delivery_log import (
    NotificationDeliveryLog as _NotificationDeliveryLog,
)

_usage_router = create_usage_router(
    SessionDep=SessionDep,
    CurrentUser=CurrentUser,
    CompanyAdminDep=CompanyAdminDep,
    AIUsageEvent=AIUsageEvent,
    company_settings_loader=_load_company_budget,
    company_settings_setter=_set_company_budget,
    internal_gate_dep=InternalServiceDep,
    notification_log_model=_NotificationDeliveryLog,
    redis_factory=_get_redis_pool,
)
api_router.include_router(_usage_router)


_streaming_router = create_streaming_router(
    SessionFactory=_AsyncSessionLocal,
    AIAgentConfig=AIAgentConfig,
    AIAgentSkillLink=AIAgentSkillLink,
    resolve_token=_resolve_token_for_stream,
    resolve_key=_resolve_key_for_stream,
)
api_router.include_router(_streaming_router)

"""LLM tenant-gate helper for integration-hub routes.

Wraps :func:`smart_llm.usage.assert_llm_allowed_for_tenant` with this
service's local plumbing (session, AIUsageEvent, company-settings
loader, NotificationDeliveryLog, Redis pool) so callers in
``routes/ai_invoke.py`` just do::

    await assert_llm_allowed(db, company_id)

before invoking ``AIService.complete``. The check raises
``BudgetExceededError`` which the route maps to HTTP 429.

Why a helper instead of a FastAPI ``Depends``: the effective
``company_id`` is resolved from either the JWT or the request body
(see ai_invoke.run_agent), so an injected Depends would have to
re-parse the body. An inline call after company_id resolution is
simpler and keeps the side-effect logic in one place.
"""

from __future__ import annotations

import uuid

from smart_llm.usage import BudgetExceededError, assert_llm_allowed_for_tenant
from sqlalchemy.ext.asyncio import AsyncSession

from integration_hub_backend.api.core.redis import get_redis_pool
from integration_hub_backend.api.models.ai_usage import AIUsageEvent
from integration_hub_backend.api.models.delivery_log import NotificationDeliveryLog


async def assert_llm_allowed(
    session: AsyncSession,
    company_id: uuid.UUID | str,
) -> None:
    """Block the call if the tenant has exhausted its monthly AI budget.

    On the **first** trip per (company, month) this also inserts a
    NotificationDeliveryLog row (so the chassis bell sees it) and
    publishes to ``alert:budget_exhausted:{company_id}`` on Redis.
    Subsequent calls within the same month are throttled via a
    SET-NX'd Redis key.
    """
    # Local import: avoid a circular dependency with main.py which imports
    # routes that depend on this helper.
    from integration_hub_backend.api.api.main import _load_company_budget

    cap = await _load_company_budget(session, str(company_id))
    redis = get_redis_pool()
    try:
        await assert_llm_allowed_for_tenant(
            session,
            company_id=str(company_id),
            UsageModel=AIUsageEvent,
            monthly_budget_usd=cap,
            notification_log_model=NotificationDeliveryLog,
            redis=redis,
        )
    except BudgetExceededError:
        # The NotificationDeliveryLog alert row was already flush()ed
        # inside assert_llm_allowed_for_tenant (on the first trip per
        # company/month) but never committed — this route's session is
        # request-scoped and get_db() only rolls back on exception, so
        # without this the bell-icon alert would silently vanish the
        # moment we raise below. Persist it before propagating.
        await session.commit()
        raise

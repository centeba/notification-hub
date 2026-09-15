"""Retention sweep activity (SB-17).

Runs the bulk retention purges RLS-exempt against this service's DB. Reads the
retention windows from env (proposed defaults from docs/data-retention.md) so an
operator can tune them without a redeploy. Driven by ``RetentionSweepWorkflow``
on a cron schedule.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

import structlog
from temporalio import activity

from integration_hub_backend.api.core.db import AsyncSessionLocal, set_bypass_rls
from integration_hub_backend.api.services.retention import (
    purge_ai_usage_events,
    purge_delivery_logs,
    purge_idle_device_tokens,
)

log = structlog.get_logger(__name__)


@dataclass
class RetentionSweepResult:
    delivery_logs: int
    device_tokens: int
    ai_usage_events: int


def _days(name: str, default: int) -> int:
    raw = os.environ.get(name, "").strip()
    try:
        return int(raw) if raw else default
    except ValueError:
        return default


@activity.defn
async def retention_sweep_activity() -> RetentionSweepResult:
    """Delete operational data past its retention window. Idempotent — a re-run
    just finds fewer (or no) expired rows."""
    delivery_days = _days("RETENTION_DELIVERY_LOG_DAYS", 90)
    device_days = _days("RETENTION_DEVICE_TOKEN_IDLE_DAYS", 180)
    ai_usage_days = _days("RETENTION_AI_USAGE_DAYS", 730)

    # Cross-tenant system maintenance selecting rows by age — not a tenant
    # request — so it runs RLS-exempt.
    set_bypass_rls()
    async with AsyncSessionLocal() as session:
        dl = await purge_delivery_logs(session, older_than_days=delivery_days)
        dt = await purge_idle_device_tokens(session, idle_days=device_days)
        au = await purge_ai_usage_events(session, older_than_days=ai_usage_days)
        await session.commit()

    result = RetentionSweepResult(delivery_logs=dl, device_tokens=dt, ai_usage_events=au)
    log.info(
        "retention_sweep_done",
        delivery_logs=dl,
        device_tokens=dt,
        ai_usage_events=au,
    )
    return result

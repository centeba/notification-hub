"""Data-retention purges (SB-17).

Time-bounded operational data is deleted past its retention window, mirroring
doc-vault's retention purge but as a periodic *bulk sweep* (these tables have no
per-row lifecycle timer). Pure functions: a session + a retention window in,
a deleted-row count out — no scheduling, no I/O beyond the delete, unit-testable.

The retention periods are the proposed defaults from ``docs/data-retention.md``
(ratify per SB-20 before enabling the sweep). Callers run these RLS-exempt
(``set_bypass_rls``) — this is cross-tenant system maintenance operating on rows
already selected by their age, not a tenant request.
"""

from datetime import UTC, datetime, timedelta
from typing import Any, cast

from sqlalchemy import delete, text
from sqlalchemy.engine import CursorResult
from sqlalchemy.ext.asyncio import AsyncSession

from integration_hub_backend.api.models.delivery_log import NotificationDeliveryLog
from integration_hub_backend.api.models.device_token import DeviceToken


def _cutoff(days: int) -> datetime:
    return datetime.now(UTC) - timedelta(days=days)


async def purge_delivery_logs(session: AsyncSession, *, older_than_days: int) -> int:
    """Delete ``notification_delivery_logs`` rows older than the window (by
    ``created_at``). Default retention 90d."""
    result = await session.execute(
        delete(NotificationDeliveryLog).where(
            NotificationDeliveryLog.created_at < _cutoff(older_than_days)
        )
    )
    return cast("CursorResult[Any]", result).rowcount or 0


async def purge_idle_device_tokens(session: AsyncSession, *, idle_days: int) -> int:
    """Delete ``device_tokens`` idle past the window — ``updated_at`` is the
    last-activity stamp (bumped on re-register/refresh via ``onupdate``), so an
    untouched token past ``idle_days`` is stale. Default 180d."""
    result = await session.execute(
        delete(DeviceToken).where(DeviceToken.updated_at < _cutoff(idle_days))
    )
    return cast("CursorResult[Any]", result).rowcount or 0


async def purge_ai_usage_events(session: AsyncSession, *, older_than_days: int) -> int:
    """Prune raw ``ai_usage_events`` past the billing + statutory window (by
    ``created_at``). Raw SQL because the table is attached via smart-llm's
    ``make_usage_model`` factory, not a local model. Default 730d (2y)."""
    result = await session.execute(
        text("DELETE FROM ai_usage_events WHERE created_at < :cutoff"),
        {"cutoff": _cutoff(older_than_days)},
    )
    return cast("CursorResult[Any]", result).rowcount or 0

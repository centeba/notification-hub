"""Metrics recording activity (claims-platform A6).

Fires once per ingested event from NotificationDispatchWorkflow → records a
generic count fact (metric_name = event_type, value = 1) so every event becomes
a queryable metric with zero domain coupling. Best-effort: never raises, so a
metrics-write hiccup can't fail notification dispatch.
"""

import uuid
from datetime import UTC, datetime

import structlog
from temporalio import activity

from integration_hub_backend.api.temporal.activities.dispatch import EventInput

log = structlog.get_logger(__name__)


@activity.defn
async def record_metric_fact_activity(event: EventInput) -> None:
    from integration_hub_backend.api.core.db import AsyncSessionLocal, set_current_org
    from integration_hub_backend.api.crud.metric_facts import record_fact

    if not event.company_id:
        return
    try:
        cid = uuid.UUID(str(event.company_id))
    except (ValueError, TypeError):
        return
    # Worker path → stamp the RLS tenant GUC (writes metric_facts; the policy
    # WITH CHECK would otherwise reject the insert once the app role is active).
    set_current_org(cid)
    try:
        async with AsyncSessionLocal() as db:
            await record_fact(
                db,
                company_id=cid,
                metric_name=event.event_type,
                value=1.0,
                dimension_keys={},
                event_type=event.event_type,
                event_id=event.event_id,
                occurred_at=datetime.now(UTC),
            )
    except Exception as exc:  # noqa: BLE001
        log.warning("record_metric_fact_failed", event_type=event.event_type, error=str(exc))

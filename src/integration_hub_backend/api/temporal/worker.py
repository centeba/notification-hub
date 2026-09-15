"""Temporal worker — registers workflows and activities, runs the worker loop."""

from __future__ import annotations

import asyncio
import os

import structlog
from smart_llm.service_runtime import graceful_shutdown_timeout as _grace_timeout
from temporalio.client import Client
from temporalio.exceptions import WorkflowAlreadyStartedError
from temporalio.worker import Worker

from integration_hub_backend.api.core.config import settings
from integration_hub_backend.api.temporal.activities.dispatch import (
    call_webhook_activity,
    check_recipient_preference_activity,
    evaluate_rules_activity,
    fetch_recipients_activity,
    log_delivery_activity,
    render_template_activity,
    resolve_channel_activity,
    send_email_activity,
    send_sms_activity,
)
from integration_hub_backend.api.temporal.activities.metrics_activities import (
    record_metric_fact_activity,
)
from integration_hub_backend.api.temporal.activities.observability_activities import (
    datadog_ship_event_activity,
    datadog_ship_log_activity,
    elasticsearch_index_document_activity,
    grafana_create_annotation_activity,
    splunk_ship_event_activity,
)
from integration_hub_backend.api.temporal.activities.retention import (
    retention_sweep_activity,
)
from integration_hub_backend.api.temporal.workflows.notification_dispatch import (
    TASK_QUEUE as NOTIFICATION_TASK_QUEUE,
)

# Scraper activities/workflows were duplicated from mit-stack into
# this service with a stale ``company_id`` column that doesn't exist
# on the shared ``scraper_sessions`` table (mit-stack owns the
# migration; the column there is ``org_id``). The duplicates are
# orphaned for deletion; mit-stack's worker handles the
# ``scraper_queue`` task queue.
from integration_hub_backend.api.temporal.workflows.notification_dispatch import (
    BulkNotificationWorkflow,
    NotificationDispatchWorkflow,
)
from integration_hub_backend.api.temporal.workflows.observability_workflow import (
    ShipObservabilityDataWorkflow,
)
from integration_hub_backend.api.temporal.workflows.retention_sweep import (
    RETENTION_SWEEP_WORKFLOW_ID,
    RetentionSweepWorkflow,
)
from integration_hub_backend.email.ingest import (
    EmailIngestWorkflow,
    dispatch_to_extractor,
    fetch_emails_via_hub,
)

log = structlog.get_logger(__name__)

# The dispatch workflow is STARTED on notification_dispatch.TASK_QUEUE
# (= "sentinelbuild-notifications", also the configured TEMPORAL_TASK_QUEUE).
# The worker MUST listen on that same queue, else every NotificationDispatch
# run sits unhandled. Previously hard-coded "notification-hub" — a queue no
# start-site uses — so notifications never dispatched. Single source of truth now.
TASK_QUEUE = NOTIFICATION_TASK_QUEUE


async def run_worker() -> None:
    log.info("worker_starting", temporal_address=settings.TEMPORAL_ADDRESS)

    client = await Client.connect(
        settings.TEMPORAL_ADDRESS,
        namespace=settings.TEMPORAL_NAMESPACE,
    )

    worker = Worker(
        client,
        task_queue=TASK_QUEUE,
        workflows=[
            NotificationDispatchWorkflow,
            BulkNotificationWorkflow,
            ShipObservabilityDataWorkflow,
            RetentionSweepWorkflow,
        ],
        activities=[
            evaluate_rules_activity,
            record_metric_fact_activity,
            fetch_recipients_activity,
            resolve_channel_activity,
            check_recipient_preference_activity,
            render_template_activity,
            send_email_activity,
            send_sms_activity,
            call_webhook_activity,
            log_delivery_activity,
            datadog_ship_event_activity,
            datadog_ship_log_activity,
            splunk_ship_event_activity,
            grafana_create_annotation_activity,
            elasticsearch_index_document_activity,
            retention_sweep_activity,
        ],
        max_concurrent_activities=50,
        max_concurrent_workflow_tasks=20,
        graceful_shutdown_timeout=_grace_timeout(),  # drain in-flight on SIGTERM
    )

    # scraper_queue worker removed — mit-stack owns scraper sessions
    # and runs that queue's worker. See comment near the imports.

    ingest_worker = Worker(
        client,
        task_queue="sentinelbuild-email-ingest",
        workflows=[EmailIngestWorkflow],
        activities=[fetch_emails_via_hub, dispatch_to_extractor],
        max_concurrent_activities=10,
        graceful_shutdown_timeout=_grace_timeout(),  # drain in-flight on SIGTERM
    )

    # SB-17 retention sweep — start the singleton cron workflow when enabled.
    # Off by default: the retention periods are proposed-pending-ratification
    # (docs/data-retention.md), so nothing is deleted until an operator sets
    # RETENTION_SWEEP_ENABLED. Starting an already-running cron is a no-op.
    if os.environ.get("RETENTION_SWEEP_ENABLED", "").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    ):
        cron = os.environ.get("RETENTION_SWEEP_CRON", "0 3 * * *")  # daily 03:00
        try:
            await client.start_workflow(
                RetentionSweepWorkflow.run,
                id=RETENTION_SWEEP_WORKFLOW_ID,
                task_queue=TASK_QUEUE,
                cron_schedule=cron,
            )
            log.info("retention_sweep_scheduled", cron=cron)
        except WorkflowAlreadyStartedError:
            log.info("retention_sweep_already_scheduled")

    log.info("workers_started", task_queues=[TASK_QUEUE, "sentinelbuild-email-ingest"])
    await asyncio.gather(worker.run(), ingest_worker.run())


if __name__ == "__main__":
    asyncio.run(run_worker())

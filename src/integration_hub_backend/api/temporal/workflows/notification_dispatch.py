"""NotificationDispatchWorkflow — main event-to-notification orchestration."""

from datetime import timedelta
from typing import Any

TASK_QUEUE = "sentinelbuild-notifications"

import structlog
from temporalio import workflow
from temporalio.common import RetryPolicy

with workflow.unsafe.imports_passed_through():
    from integration_hub_backend.api.temporal.activities.dispatch import (
        EventInput,
        call_webhook_activity,
        check_recipient_preference_activity,
        evaluate_rules_activity,
        fetch_recipients_activity,
        log_delivery_activity,
        render_template_activity,
        resolve_channel_activity,
        send_email_activity,
        send_push_activity,
        send_sms_activity,
    )
    from integration_hub_backend.api.temporal.activities.metrics_activities import (
        record_metric_fact_activity,
    )

log = structlog.get_logger(__name__)

_RETRY_POLICY = RetryPolicy(
    initial_interval=timedelta(seconds=5),
    backoff_coefficient=2.0,
    maximum_interval=timedelta(minutes=2),
    maximum_attempts=3,
)

_ACTIVITY_TIMEOUT = timedelta(minutes=2)


@workflow.defn
class NotificationDispatchWorkflow:
    """
    Orchestrates end-to-end notification dispatch for a single event.

    Flow:
    1. Evaluate rules → find matching rules for this event type
    2. For each rule → fetch recipients → render template → send per channel → log
    """

    @workflow.run
    async def run(self, event: EventInput) -> dict[str, Any]:
        workflow.logger.info("dispatch_started", event_type=event.event_type)

        # A6 — record a generic metric fact for EVERY event (count per event_type),
        # before the notification-rule early-return so metrics capture all events.
        # The activity is best-effort (never raises), so it can't fail dispatch.
        await workflow.execute_activity(
            record_metric_fact_activity,
            event,
            start_to_close_timeout=_ACTIVITY_TIMEOUT,
            retry_policy=_RETRY_POLICY,
        )

        # Step 1: Evaluate rules
        matching_rules = await workflow.execute_activity(
            evaluate_rules_activity,
            event,
            start_to_close_timeout=_ACTIVITY_TIMEOUT,
            retry_policy=_RETRY_POLICY,
        )

        if not matching_rules:
            workflow.logger.info("no_rules_matched", event_type=event.event_type)
            return {"dispatched": 0}

        total_dispatched = 0

        for rule in matching_rules:
            # Step 2: Fetch recipients
            recipients = await workflow.execute_activity(
                fetch_recipients_activity,
                args=[rule, event.company_id, event.payload],
                start_to_close_timeout=_ACTIVITY_TIMEOUT,
                retry_policy=_RETRY_POLICY,
            )

            if not recipients:
                continue

            for recipient in recipients:
                language = recipient.get("language", "en")
                template_id = rule["template_id"]

                # Step 3: Render template per channel
                channel_ids = rule.get("channel_ids", [])

                # Determine channels from DB (resolve IDs to names)
                # For simplicity in the workflow, we pass channel names stored in rule
                # The rule's channel_ids are UUIDs; we resolve them in the activity
                for channel_id in channel_ids:
                    channel_name = await self._resolve_channel_name(channel_id)
                    if not channel_name:
                        continue

                    # A8 — honor the recipient's per-channel preference
                    # (channel mute + quiet hours). Skip silently if disallowed.
                    pref_ok = await workflow.execute_activity(
                        check_recipient_preference_activity,
                        args=[recipient.get("user_id"), event.company_id, channel_id],
                        start_to_close_timeout=_ACTIVITY_TIMEOUT,
                        retry_policy=_RETRY_POLICY,
                    )
                    if not pref_ok:
                        continue

                    rendered = await workflow.execute_activity(
                        render_template_activity,
                        args=[template_id, language, event.payload, channel_name],
                        start_to_close_timeout=_ACTIVITY_TIMEOUT,
                        retry_policy=_RETRY_POLICY,
                    )

                    if not rendered:
                        continue

                    delivery_result: dict[str, Any] = {}

                    # Step 4: Send via appropriate channel
                    if channel_name == "email" and recipient.get("email"):
                        # Fetch from_address from company settings (cached in activity)
                        delivery_result = await workflow.execute_activity(
                            send_email_activity,
                            args=[
                                recipient,
                                rendered,
                                "notifications@example.com",  # Will be resolved from company settings
                                "Notification Hub",
                            ],
                            start_to_close_timeout=_ACTIVITY_TIMEOUT,
                            retry_policy=_RETRY_POLICY,
                        )

                    elif channel_name == "sms" and recipient.get("phone"):
                        delivery_result = await workflow.execute_activity(
                            send_sms_activity,
                            args=[recipient, rendered, event.company_id],
                            start_to_close_timeout=_ACTIVITY_TIMEOUT,
                            retry_policy=_RETRY_POLICY,
                        )

                    elif channel_name == "webhook":
                        # webhook endpoint_id comes from rule config
                        endpoint_id = (rule.get("recipient_config") or {}).get(
                            "webhook_endpoint_id"
                        )
                        if endpoint_id:
                            delivery_result = await workflow.execute_activity(
                                call_webhook_activity,
                                args=[endpoint_id, rendered, event.payload],
                                start_to_close_timeout=_ACTIVITY_TIMEOUT,
                                retry_policy=_RETRY_POLICY,
                            )

                    elif channel_name == "push":
                        delivery_result = await workflow.execute_activity(
                            send_push_activity,
                            args=[recipient, rendered, event.company_id],
                            start_to_close_timeout=_ACTIVITY_TIMEOUT,
                            retry_policy=_RETRY_POLICY,
                        )

                    # Step 5: Log delivery
                    await workflow.execute_activity(
                        log_delivery_activity,
                        args=[
                            rule["rule_id"],
                            event.event_type,
                            event.payload,
                            channel_name,
                            recipient.get("user_id"),
                            recipient.get("email") or recipient.get("phone"),
                            delivery_result.get("status", "failed"),
                            delivery_result.get("provider_message_id"),
                            delivery_result.get("error"),
                        ],
                        start_to_close_timeout=_ACTIVITY_TIMEOUT,
                        retry_policy=RetryPolicy(maximum_attempts=5),
                    )
                    total_dispatched += 1

        workflow.logger.info("dispatch_completed", total_dispatched=total_dispatched)
        return {"dispatched": total_dispatched}

    async def _resolve_channel_name(self, channel_id: str) -> str | None:
        """Resolve channel UUID → name via the resolve_channel activity."""
        return await workflow.execute_activity(
            resolve_channel_activity,
            channel_id,
            start_to_close_timeout=_ACTIVITY_TIMEOUT,
            retry_policy=_RETRY_POLICY,
        )


@workflow.defn
class BulkNotificationWorkflow:
    """
    Fan-out workflow for admin-triggered bulk notifications.
    Uses Continue-as-New after 1000 recipients to avoid history limits.
    """

    @workflow.run
    async def run(
        self,
        event: EventInput,
        offset: int = 0,
        total_dispatched: int = 0,
    ) -> dict[str, Any]:
        BATCH_SIZE = 100
        MAX_PER_EXECUTION = 1000

        dispatched_this_run = 0

        while dispatched_this_run < MAX_PER_EXECUTION:
            # Process a batch via child dispatch workflow
            child_event = EventInput(
                event_id=f"{event.event_id}_bulk_{offset}",
                event_type=event.event_type,
                company_id=event.company_id,
                payload={**event.payload, "_bulk_offset": offset, "_bulk_limit": BATCH_SIZE},
            )

            result = await workflow.execute_child_workflow(
                NotificationDispatchWorkflow.run,
                child_event,
                id=f"dispatch_{child_event.event_id}",
            )

            batch_dispatched = result.get("dispatched", 0)
            dispatched_this_run += batch_dispatched
            total_dispatched += batch_dispatched
            offset += BATCH_SIZE

            if batch_dispatched < BATCH_SIZE:
                break  # No more recipients

        if dispatched_this_run >= MAX_PER_EXECUTION:
            # Continue-as-New to avoid Temporal history limits.
            # pre-existing bug fixed: continue_as_new takes a single positional
            # ``arg`` plus keyword ``args=[...]``; passing three positionals raised
            # at runtime. Pass them as ``args=[...]`` matching run()'s signature.
            workflow.continue_as_new(args=[event, offset, total_dispatched])

        return {"total_dispatched": total_dispatched}

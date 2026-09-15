"""Temporal workflow for observability integrations."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from typing import Any

from temporalio import workflow
from temporalio.common import RetryPolicy

with workflow.unsafe.imports_passed_through():
    from integration_hub_backend.api.temporal.activities.observability_activities import (
        ShipRequest,
        datadog_ship_event_activity,
        datadog_ship_log_activity,
        elasticsearch_index_document_activity,
        grafana_create_annotation_activity,
        splunk_ship_event_activity,
    )

_RETRY_POLICY = RetryPolicy(
    initial_interval=timedelta(seconds=5),
    backoff_coefficient=2.0,
    maximum_interval=timedelta(minutes=5),
    maximum_attempts=5,
)

_ACTIVITY_TIMEOUT = timedelta(minutes=2)


@dataclass
class ObservabilitySignal:
    integration_type: str  # datadog | splunk | grafana | elasticsearch
    operation: str  # e.g. send_event, send_log
    data: dict[str, Any]
    # Tenant whose per-company connector credential should be preferred
    # (falls back to the global SystemIntegration when unset / absent).
    company_id: str | None = None


@workflow.defn
class ShipObservabilityDataWorkflow:
    """
    Workflow to reliably ship observability data to external platforms.
    """

    @workflow.run
    async def run(self, signal: ObservabilitySignal) -> dict[str, Any]:
        req = ShipRequest(data=signal.data, company_id=signal.company_id)

        if signal.integration_type == "datadog":
            if signal.operation == "send_event":
                return await workflow.execute_activity(
                    datadog_ship_event_activity,
                    req,
                    start_to_close_timeout=_ACTIVITY_TIMEOUT,
                    retry_policy=_RETRY_POLICY,
                )
            elif signal.operation == "send_log":
                return await workflow.execute_activity(
                    datadog_ship_log_activity,
                    req,
                    start_to_close_timeout=_ACTIVITY_TIMEOUT,
                    retry_policy=_RETRY_POLICY,
                )

        elif signal.integration_type == "splunk":
            if signal.operation == "send_event":
                return await workflow.execute_activity(
                    splunk_ship_event_activity,
                    req,
                    start_to_close_timeout=_ACTIVITY_TIMEOUT,
                    retry_policy=_RETRY_POLICY,
                )

        elif signal.integration_type == "grafana":
            if signal.operation == "create_annotation":
                return await workflow.execute_activity(
                    grafana_create_annotation_activity,
                    req,
                    start_to_close_timeout=_ACTIVITY_TIMEOUT,
                    retry_policy=_RETRY_POLICY,
                )

        elif signal.integration_type == "elasticsearch":
            if signal.operation == "index_document":
                return await workflow.execute_activity(
                    elasticsearch_index_document_activity,
                    req,
                    start_to_close_timeout=_ACTIVITY_TIMEOUT,
                    retry_policy=_RETRY_POLICY,
                )

        raise ValueError(
            f"Unsupported observability operation: {signal.integration_type}/{signal.operation}"
        )

"""Retention sweep workflow (SB-17).

A thin cron workflow: Temporal re-invokes it each tick (see the ``cron_schedule``
at start), and each run executes one retention sweep activity. Deterministic — no
timers or logic of its own; the activity does the dated deletes.
"""

from __future__ import annotations

from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy

with workflow.unsafe.imports_passed_through():
    from integration_hub_backend.api.temporal.activities.retention import (
        RetentionSweepResult,
    )

# Fixed id so the cron schedule is a singleton (starting it again is a no-op).
RETENTION_SWEEP_WORKFLOW_ID = "retention-sweep"


@workflow.defn
class RetentionSweepWorkflow:
    @workflow.run
    async def run(self) -> RetentionSweepResult:
        result: RetentionSweepResult = await workflow.execute_activity(
            "retention_sweep_activity",
            start_to_close_timeout=timedelta(minutes=10),
            retry_policy=RetryPolicy(maximum_attempts=3),
        )
        return result

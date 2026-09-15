"""Scheduled email ingestion via Temporal.

Replaces the legacy imaplib IMAPPoller. Emails are read through the integration-hub's
own OAuth2 connectors (Gmail API / MS Graph), then forwarded to the email-extractor
Temporal task queue for LLM extraction.

Usage — start a schedule from your management script or the integration-hub worker:
    await client.create_schedule(
        "email-ingest-<org_id>-<credential_id>",
        Schedule(
            action=ScheduleActionStartWorkflow(
                EmailIngestWorkflow.run,
                EmailIngestParams(org_id=..., credential_id=..., provider="gmail"),
                id="email-ingest-run",
                task_queue="sentinelbuild-notifications",
            ),
            spec=ScheduleSpec(intervals=[ScheduleIntervalSpec(every=timedelta(minutes=5))]),
        ),
    )
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from typing import Any

import structlog
from temporalio import activity, workflow
from temporalio.common import RetryPolicy

log = structlog.get_logger(__name__)

_NO_RETRY = RetryPolicy(maximum_attempts=1)
_DEFAULT_RETRY = RetryPolicy(maximum_attempts=3, initial_interval=timedelta(seconds=5))


@dataclass
class EmailIngestParams:
    org_id: str
    credential_id: str  # integration-hub credential UUID
    provider: str  # "gmail" | "outlook"
    folder: str = "Inbox"
    subject_filter: str = ""
    max_results: int = 20
    context_notes: str = ""


@dataclass
class _FetchEmailsParams:
    org_id: str
    credential_id: str
    provider: str
    folder: str
    subject_filter: str
    max_results: int


@dataclass
class _DispatchParams:
    email_data: dict[str, Any]
    context_notes: str
    org_id: str


@activity.defn
async def fetch_emails_via_hub(params: _FetchEmailsParams) -> list[dict[str, Any]]:
    """Call integration-hub's OAuth2 email-reading endpoints (Gmail / Outlook)."""
    import httpx

    from integration_hub_backend.api.core.config import settings as hub_settings

    hub_base = (
        hub_settings.API_BASE_URL
        if hasattr(hub_settings, "API_BASE_URL")
        else "http://localhost:8005"
    )
    headers = {
        "Authorization": f"Bearer {hub_settings.INTERNAL_API_KEY}",
        "Content-Type": "application/json",
    }

    if params.provider == "gmail":
        payload = {
            "credential_id": params.credential_id,
            "query": params.subject_filter or "is:unread",
            "max_results": params.max_results,
        }
        endpoint = f"{hub_base}/api/v1/integrations/gmail/read"
        key_messages = "messages"
        body_key = "body_plain"
        id_key = "id"
    elif params.provider == "outlook":
        filter_q = (
            f"isRead eq false and contains(subject, '{params.subject_filter}')"
            if params.subject_filter
            else "isRead eq false"
        )
        payload = {
            "credential_id": params.credential_id,
            "folder": params.folder,
            "filter_query": filter_q,
            "max_results": params.max_results,
        }
        endpoint = f"{hub_base}/api/v1/integrations/outlook/read"
        key_messages = "messages"
        body_key = "body_content"
        id_key = "id"
    else:
        raise ValueError(f"Unsupported provider: {params.provider!r}. Use 'gmail' or 'outlook'.")

    async with httpx.AsyncClient(timeout=60) as client:
        resp = await client.post(endpoint, headers=headers, json=payload)
        resp.raise_for_status()

    msgs = resp.json().get(key_messages, [])
    log.info("emails_fetched", provider=params.provider, count=len(msgs), org_id=params.org_id)

    return [
        {
            "message_id": m.get(id_key, ""),
            "subject": m.get("subject", ""),
            "sender": m.get("from", ""),
            "body": m.get(body_key, m.get("snippet", m.get("preview", ""))),
            "date": m.get("date", ""),
        }
        for m in msgs
    ]


@activity.defn
async def dispatch_to_extractor(params: _DispatchParams) -> str:
    """Forward a single email to the email-extractor Temporal task queue."""
    import uuid

    from temporalio.client import Client

    from integration_hub_backend.api.core.config import settings as hub_settings

    temporal_host = getattr(hub_settings, "TEMPORAL_HOST", "localhost:7233")
    client = await Client.connect(temporal_host)

    workflow_id = f"email-ingest-{params.org_id}-{uuid.uuid4()}"
    handle = await client.start_workflow(
        "ProcessEmailWorkflow",
        args=[params.email_data, params.context_notes],
        id=workflow_id,
        task_queue="email-extraction-task-queue",
    )
    log.info(
        "email_dispatched_to_extractor",
        workflow_id=handle.id,
        org_id=params.org_id,
        subject=params.email_data.get("subject"),
    )
    return handle.id


@workflow.defn
class EmailIngestWorkflow:
    """Polls OAuth2 email (Gmail/Outlook) and fans out to the email-extractor queue."""

    @workflow.run
    async def run(self, params: EmailIngestParams) -> dict[str, Any]:
        emails = await workflow.execute_activity(
            fetch_emails_via_hub,
            _FetchEmailsParams(
                org_id=params.org_id,
                credential_id=params.credential_id,
                provider=params.provider,
                folder=params.folder,
                subject_filter=params.subject_filter,
                max_results=params.max_results,
            ),
            start_to_close_timeout=timedelta(minutes=2),
            retry_policy=_DEFAULT_RETRY,
        )

        dispatched = 0
        for email_data in emails:
            await workflow.execute_activity(
                dispatch_to_extractor,
                _DispatchParams(
                    email_data=email_data,
                    context_notes=params.context_notes,
                    org_id=params.org_id,
                ),
                start_to_close_timeout=timedelta(seconds=30),
                retry_policy=_NO_RETRY,
            )
            dispatched += 1

        return {"fetched": len(emails), "dispatched": dispatched, "org_id": params.org_id}

"""Temporal activities for observability integrations."""

from dataclasses import dataclass
from typing import Any

import httpx
import structlog
from temporalio import activity

from integration_hub_backend.api.core.db import AsyncSessionLocal, set_current_org

log = structlog.get_logger(__name__)


@dataclass
class ShipRequest:
    data: dict[str, Any]
    # Tenant whose per-company connector credential should be preferred
    # (falls back to the global SystemIntegration when unset / absent).
    company_id: str | None = None


def _get_datadog_endpoints(site: str) -> dict[str, str]:
    """Return Datadog API and log-intake base URLs for a given site."""
    site_map = {
        "us1": ("https://api.datadoghq.com", "https://http-intake.logs.datadoghq.com"),
        "us3": ("https://us3.datadoghq.com", "https://http-intake.logs.us3.datadoghq.com"),
        "us5": ("https://us5.datadoghq.com", "https://http-intake.logs.us5.datadoghq.com"),
        "eu1": ("https://api.datadoghq.eu", "https://http-intake.logs.datadoghq.eu"),
        "ap1": ("https://api.ap1.datadoghq.com", "https://http-intake.logs.ap1.datadoghq.com"),
    }
    api_url, logs_url = site_map.get(site, site_map["us1"])
    return {"api": api_url, "logs": logs_url}


async def _get_secrets(expected_type: str, company_id: str | None = None) -> dict[str, Any]:
    """Fetch connector secrets, preferring the per-company credential.

    Falls back to the global ``SystemIntegration`` when the tenant has no
    Connect-UI credential for this connector (see ``integration_secrets``).
    """
    from integration_hub_backend.api.services.integration_secrets import (
        resolve_integration_secrets,
    )

    # Worker path → stamp the RLS tenant GUC so the per-company
    # integration_credentials lookup is visible. A None company_id means the
    # platform-global SystemIntegration fallback (not RLS'd) — leave unstamped.
    if company_id:
        set_current_org(company_id)
    async with AsyncSessionLocal() as db:
        secrets = await resolve_integration_secrets(db, expected_type, company_id)
    if not secrets:
        raise ValueError(f"No credential for {expected_type} (neither per-company nor global).")
    return secrets


@activity.defn
async def datadog_ship_event_activity(req: ShipRequest) -> dict[str, Any]:
    secrets = await _get_secrets("datadog", req.company_id)
    api_key: Any = secrets.get("api_key")
    site = secrets.get("site", "us1")

    endpoints = _get_datadog_endpoints(site)

    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"{endpoints['api']}/api/v1/events",
            headers={"DD-API-KEY": api_key},
            json=req.data,
        )
        resp.raise_for_status()
        body: dict[str, Any] = resp.json()
        return body


@activity.defn
async def datadog_ship_log_activity(req: ShipRequest) -> dict[str, Any]:
    secrets = await _get_secrets("datadog", req.company_id)
    api_key: Any = secrets.get("api_key")
    site = secrets.get("site", "us1")

    endpoints = _get_datadog_endpoints(site)

    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"{endpoints['logs']}/api/v2/logs",
            headers={"DD-API-KEY": api_key},
            json=req.data,
        )
        resp.raise_for_status()
        return {"status": "ok"}


@activity.defn
async def splunk_ship_event_activity(req: ShipRequest) -> dict[str, Any]:
    secrets = await _get_secrets("splunk", req.company_id)
    hec_token = secrets.get("hec_token")
    hec_url = secrets.get("hec_url", "").rstrip("/") + "/services/collector/event"

    async with httpx.AsyncClient() as client:
        resp = await client.post(
            hec_url,
            headers={"Authorization": f"Splunk {hec_token}"},
            json=req.data,
        )
        resp.raise_for_status()
        body: dict[str, Any] = resp.json()
        return body


@activity.defn
async def grafana_create_annotation_activity(req: ShipRequest) -> dict[str, Any]:
    secrets = await _get_secrets("grafana", req.company_id)
    api_key = secrets.get("api_key")
    url = f"{secrets.get('url', '').rstrip('/')}/api/annotations"

    async with httpx.AsyncClient() as client:
        resp = await client.post(
            url,
            headers={"Authorization": f"Bearer {api_key}"},
            json=req.data,
        )
        resp.raise_for_status()
        body: dict[str, Any] = resp.json()
        return body


@activity.defn
async def elasticsearch_index_document_activity(req: ShipRequest) -> dict[str, Any]:
    secrets = await _get_secrets("elasticsearch", req.company_id)
    url = secrets.get("url", "").rstrip("/")
    index = req.data.get("index", "logs")
    doc = req.data.get("document", {})
    doc_id = req.data.get("id")

    path = f"/{index}/_doc"
    if doc_id:
        path = f"/{index}/_doc/{doc_id}"

    auth: tuple[str, str] | None = None
    headers: dict[str, str] = {}
    username = secrets.get("username")
    password = secrets.get("password")
    if secrets.get("api_key"):
        headers["Authorization"] = f"ApiKey {secrets.get('api_key')}"
    elif username and password:
        auth = (username, password)

    async with httpx.AsyncClient(auth=auth) as client:
        resp = await client.post(
            f"{url}{path}",
            headers=headers,
            json=doc,
        )
        resp.raise_for_status()
        body: dict[str, Any] = resp.json()
        return body

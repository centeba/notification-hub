"""Service for managing global observability integrations."""

import uuid
from typing import Any

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from integration_hub_backend.api.crud.system_integrations import (
    get_system_decrypted,
    get_system_integration,
    list_system_integrations,
    update_system_integration,
)
from integration_hub_backend.api.models.system_integration import NotificationSystemIntegration


class ObservabilityService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def list_global_configs(self) -> list[NotificationSystemIntegration]:
        """List all global observability settings."""
        return await list_system_integrations(self.db)

    async def update_global_config(
        self,
        name: str,
        is_enabled: bool | None = None,
        config: dict[str, Any] | None = None,
    ) -> NotificationSystemIntegration:
        """Update or create global integration config."""
        return await update_system_integration(self.db, name, is_enabled, config)

    async def get_decrypted_config(self, name: str) -> dict[str, Any]:
        """Get the configuration for a specific platform (decrypted)."""
        integration = await get_system_integration(self.db, name)
        if not integration:
            return {}
        return get_system_decrypted(integration)

    async def push_data(
        self,
        integration_type: str,
        operation: str,
        data: dict[str, Any],
        company_id: Any | None = None,
    ) -> str:
        """
        Trigger a Temporal workflow to ship observability data.

        ``company_id`` (when provided) makes the shipping activity prefer the
        tenant's per-company Connect-UI credential, falling back to the
        global SystemIntegration. Returns the workflow run ID.
        """
        from integration_hub_backend.api.temporal.client import get_temporal_client

        client = await get_temporal_client()

        from integration_hub_backend.api.temporal.workflows.observability_workflow import (
            ObservabilitySignal,
        )

        handle = await client.start_workflow(
            "ShipObservabilityDataWorkflow",
            ObservabilitySignal(
                integration_type=integration_type,
                operation=operation,
                data=data,
                company_id=str(company_id) if company_id else None,
            ),
            id=f"obs-{integration_type}-{uuid.uuid4().hex[:8]}",
            task_queue="notification-hub",
        )
        # pre-existing bug fixed: WorkflowHandle has no ``result_id`` (which raised
        # AttributeError). start_workflow populates ``result_run_id`` with the
        # started run's id (``run_id`` stays None for start_workflow handles).
        run_id = handle.result_run_id
        return run_id or ""

    async def datadog_query_logs(
        self, query: str, time_from: str = "now-1h", time_to: str = "now", limit: int = 10
    ) -> list[dict[str, Any]]:
        """Query Datadog logs."""
        config = await self.get_decrypted_config("datadog")
        api_key = config.get("api_key")
        app_key = config.get("app_key")
        site = config.get("site", "datadoghq.com")

        if not api_key or not app_key:
            return [{"error": "Datadog API or APP key not configured globally."}]

        url = f"https://api.{site}/api/v2/logs/events/search"
        headers = {
            "DD-API-KEY": api_key,
            "DD-APPLICATION-KEY": app_key,
            "Content-Type": "application/json",
        }
        payload = {
            "filter": {"query": query, "from": time_from, "to": time_to},
            "page": {"limit": limit},
        }

        async with httpx.AsyncClient() as client:
            resp = await client.post(url, headers=headers, json=payload)
            if resp.is_error:
                return [{"error": f"Datadog query failed: {resp.status_code} {resp.text}"}]
            data: list[dict[str, Any]] = resp.json().get("data", [])
            return data

    async def elasticsearch_search(
        self, index: str, query: str, size: int = 10
    ) -> list[dict[str, Any]]:
        """Search Elasticsearch indices."""
        config = await self.get_decrypted_config("elasticsearch")
        url = config.get("url", "").rstrip("/")
        if not url:
            return [{"error": "Elasticsearch URL not configured."}]

        headers = {"Content-Type": "application/json"}
        if config.get("api_key"):
            headers["Authorization"] = f"ApiKey {config.get('api_key')}"

        auth: tuple[str, str] | None = None
        username = config.get("username")
        password = config.get("password")
        if not config.get("api_key") and username and password:
            auth = (username, password)

        payload = {"query": {"query_string": {"query": query}}, "size": size}

        async with httpx.AsyncClient(auth=auth) as client:
            resp = await client.post(f"{url}/{index}/_search", headers=headers, json=payload)
            if resp.is_error:
                return [{"error": f"Elasticsearch search failed: {resp.status_code} {resp.text}"}]
            hits = resp.json().get("hits", {}).get("hits", [])
            return [h.get("_source", {}) for h in hits]

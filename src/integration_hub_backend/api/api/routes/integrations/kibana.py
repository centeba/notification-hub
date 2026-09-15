"""Kibana integration - dashboard discovery (Global)."""

from __future__ import annotations

from typing import Any

import httpx
from fastapi import APIRouter, HTTPException, status

from integration_hub_backend.api.api.deps import ApiKeyDep, SessionDep
from integration_hub_backend.api.services.integration_secrets import (
    resolve_integration_secrets,
)

router = APIRouter(prefix="/kibana", tags=["integrations"])


@router.get("/dashboards")
async def list_kibana_dashboards(db: SessionDep, api_key: ApiKeyDep) -> list[dict[str, Any]]:
    """List dashboards from the tenant's (or global) Kibana instance.

    Prefers the company's Connect-UI credential, falling back to the global
    SystemIntegration. Supports API-key auth (Connect form) or
    username/password (global config).
    """
    api_key.require_scope("integrations:kibana")

    config = await resolve_integration_secrets(db, "kibana", api_key.company_id)

    url = config.get("url", "").rstrip("/")
    api_key_secret = config.get("api_key")
    username = config.get("username")
    password = config.get("password")

    if not url:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Kibana URL not configured"
        )

    auth = None
    headers = {"kbn-xsrf": "true"}
    if api_key_secret:
        headers["Authorization"] = f"ApiKey {api_key_secret}"
    elif username and password:
        auth = (username, password)

    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"{url}/api/saved_objects/_find",
            params={"type": "dashboard", "per_page": 100},
            auth=auth,
            headers=headers,
        )
        if resp.is_error:
            raise HTTPException(status_code=resp.status_code, detail=f"Kibana error: {resp.text}")

        data = resp.json()
        return [
            {
                "id": obj["id"],
                "title": obj["attributes"]["title"],
                "updated_at": obj["updated_at"],
            }
            for obj in data.get("saved_objects", [])
        ]

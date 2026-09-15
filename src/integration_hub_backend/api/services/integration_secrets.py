"""Resolve connector secrets, preferring per-company credentials.

The connector *action* routes (datadog/splunk/grafana/elasticsearch/kibana)
historically read a single **global** ``SystemIntegration`` row. With the
Integration Hub "Connect" UI, a company admin can store a **per-company**
credential (``integration_credentials`` tagged with the connector key via
``POST /credentials/connect``).

This resolver prefers that per-company credential and **falls back** to the
global ``SystemIntegration`` — so the Connect UI actually drives the
connector while any existing platform-wide config keeps working untouched.

The connector key (``integration_credentials.connector``) equals the
integration type for these observability connectors (``datadog`` … ).
"""

from __future__ import annotations

import uuid
from typing import Any

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from integration_hub_backend.api.crud.integration_credentials import (
    get_decrypted,
    list_credentials,
)
from integration_hub_backend.api.crud.system_integrations import (
    get_system_decrypted,
    get_system_integration,
)

log = structlog.get_logger(__name__)


def _normalize(secrets: dict[str, Any]) -> dict[str, Any]:
    """Bridge Connect-form field names to what the action code reads.

    The Connect dialog stores ``base_url`` for grafana/elasticsearch/kibana,
    but the activities/routes read ``url`` (the global SystemIntegration's
    key). Alias it so a credential from either source works unchanged.
    """
    out = dict(secrets)
    if not out.get("url") and out.get("base_url"):
        out["url"] = out["base_url"]
    return out


async def resolve_integration_secrets(
    db: AsyncSession, integration_type: str, company_id: Any | None = None
) -> dict[str, Any]:
    """Return decrypted secrets for ``integration_type``.

    Precedence: per-company ``integration_credentials`` (tagged with the
    connector key) → global enabled ``SystemIntegration`` → ``{}``.
    """
    # 1) Per-company credential (Connect UI), if present.
    if company_id:
        try:
            cid = uuid.UUID(str(company_id))
        except (ValueError, TypeError, AttributeError):
            cid = None
        if cid is not None:
            rows = await list_credentials(db, company_id=cid, connector=integration_type)
            if rows:
                # Most-recent first (list_credentials orders by created_at desc).
                return _normalize(get_decrypted(rows[0]))
    # 2) Global SystemIntegration fallback. Defensive: if the global lookup
    # errors (e.g. the table is absent in an env that never seeded global
    # config), degrade to "no secrets" rather than surfacing a DB error —
    # the per-company credential is the primary path, and callers handle an
    # empty result with a clean "not configured" message.
    try:
        integration = await get_system_integration(db, integration_type)
    except Exception:
        log.warning(
            "global_integration_lookup_failed",
            integration_type=integration_type,
            exc_info=True,
        )
        return {}
    if integration and integration.is_enabled:
        return _normalize(get_system_decrypted(integration))
    return {}

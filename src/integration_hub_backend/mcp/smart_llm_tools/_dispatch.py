"""One service-dispatch for every integration-hub tool.

Both transports route through :func:`dispatch` — the MCP server
(``mcp/server.py``) and the smart-llm action tools in this package — so a
tool added to ``mcp/tools.TOOL_DEFINITIONS`` is built and called the same
way whichever way it's invoked.
"""

from typing import Any

from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from integration_hub_backend.api.services.connector_service import ConnectorService
from integration_hub_backend.api.services.email_service import EmailService
from integration_hub_backend.api.services.google_drive_service import GoogleDriveService
from integration_hub_backend.api.services.observability_service import ObservabilityService
from integration_hub_backend.api.services.postgres_service import PostgresService
from integration_hub_backend.api.services.rule_service import RuleService
from integration_hub_backend.api.services.stripe_service import StripeService
from integration_hub_backend.mcp.tools import TOOL_DEFINITIONS


def _service_for(kind: str, db: AsyncSession) -> Any:
    if kind == "email_service":
        return EmailService(db)
    if kind == "google_drive_service":
        return GoogleDriveService(ObservabilityService(db))
    if kind == "stripe_service":
        return StripeService(ObservabilityService(db))
    if kind == "observability_service":
        return ObservabilityService(db)
    if kind == "postgres_service":
        return PostgresService(db)
    if kind == "rule_service":
        # Rule Builder agent's toolset — read/create notification rules.
        return RuleService(db)
    if kind == "connector_service":
        # Inbound claims/FNOL gateway (A4) — list + drive connectors.
        return ConnectorService(db)
    raise ValueError(f"Unknown service: {kind}")


async def dispatch(name: str, args: BaseModel, *, db_session: AsyncSession) -> Any:
    """Call the service method ``TOOL_DEFINITIONS[name]`` names with the
    validated ``args``. Returns whatever the method returns (typically a
    list/dict)."""
    info = TOOL_DEFINITIONS[name]
    service = _service_for(info["service"], db_session)
    method = getattr(service, info["method"])
    return await method(**args.model_dump())

"""MCP Server for the Integration Hub."""

import asyncio
import json
import logging
from typing import Any

import httpx
import mcp.types as types
from mcp.server import Server
from mcp.server.stdio import stdio_server
from pydantic import ValidationError

from integration_hub_backend.api.core.db import AsyncSessionLocal
from integration_hub_backend.api.services.connector_service import ConnectorService
from integration_hub_backend.api.services.email_service import EmailService
from integration_hub_backend.api.services.google_drive_service import GoogleDriveService
from integration_hub_backend.api.services.observability_service import ObservabilityService
from integration_hub_backend.api.services.postgres_service import PostgresService
from integration_hub_backend.api.services.rule_service import RuleService
from integration_hub_backend.api.services.stripe_service import StripeService
from integration_hub_backend.mcp.tools import TOOL_DEFINITIONS

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("integration-hub-mcp")

app = Server("integration-hub")


# mcp ships py.typed but leaves its Server decorators unannotated.
@app.list_tools()  # type: ignore[no-untyped-call, untyped-decorator]
async def list_tools() -> list[types.Tool]:
    """List available integration tools."""
    tools = []
    for name, info in TOOL_DEFINITIONS.items():
        tools.append(
            types.Tool(
                name=name,
                description=info["description"],
                inputSchema=info["args_model"].model_json_schema(),
            )
        )
    return tools


@app.call_tool()  # type: ignore[untyped-decorator]
async def call_tool(
    name: str, arguments: dict[str, Any]
) -> list[types.TextContent | types.ImageContent | types.EmbeddedResource]:
    """Execute an integration tool."""
    if name not in TOOL_DEFINITIONS:
        raise ValueError(f"Tool not found: {name}")

    info = TOOL_DEFINITIONS[name]
    args_model = info["args_model"]

    # Validate arguments early, but inside a try block
    try:
        args = args_model(**arguments)

        async with AsyncSessionLocal() as db:
            # Instantiate the requested service
            service: Any
            if info["service"] == "email_service":
                service = EmailService(db)
            elif info["service"] == "google_drive_service":
                obs_service = ObservabilityService(db)
                service = GoogleDriveService(obs_service)
            elif info["service"] == "stripe_service":
                obs_service = ObservabilityService(db)
                service = StripeService(obs_service)
            elif info["service"] == "observability_service":
                service = ObservabilityService(db)
            elif info["service"] == "postgres_service":
                service = PostgresService(db)
            elif info["service"] == "rule_service":
                # Rule Builder agent's toolset — read/create notification rules
                # directly against the DB (same shape as the other services).
                service = RuleService(db)
            elif info["service"] == "connector_service":
                # Inbound claims/FNOL gateway (A4) — list + drive connectors.
                service = ConnectorService(db)
            else:
                raise ValueError(f"Unknown service: {info['service']}")

            # Call the method
            method = getattr(service, info["method"])
            result = await method(**args.model_dump())

            # Format result as JSON for better structured data delivery to the agent
            result_str = json.dumps(result, indent=2, default=str)

            return [types.TextContent(type="text", text=result_str)]
    except httpx.HTTPStatusError as e:
        logger.error(
            f"HTTP API error executing tool {name}: {e.response.status_code} - {e.response.text}"
        )
        return [
            types.TextContent(
                type="text",
                text=f"API Error: HTTP {e.response.status_code}\nResponse: {e.response.text}",
            )
        ]
    except (ValueError, ValidationError) as e:
        logger.warning(f"Validation/Configuration error executing tool {name}: {e}")
        return [types.TextContent(type="text", text=f"Validation Error: {e!s}")]
    except Exception as e:
        logger.exception(f"Unexpected error executing tool {name}")
        return [types.TextContent(type="text", text=f"Unexpected Error: {e!s}")]


async def run() -> None:
    """Run the MCP server using stdio."""
    async with stdio_server() as (read_stream, write_stream):
        await app.run(read_stream, write_stream, app.create_initialization_options())


if __name__ == "__main__":
    asyncio.run(run())

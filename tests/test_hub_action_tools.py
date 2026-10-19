"""integration-hub owns its smart-llm action tools (roadmap 2.9): importing
``integration_hub_backend.mcp.smart_llm_tools`` registers them, and the one
``dispatch`` the MCP server shares can build every service TOOL_DEFINITIONS
names."""

from unittest.mock import MagicMock

import pytest
from smart_llm.base import ActionTool
from smart_llm.registry import get_tool_meta

import integration_hub_backend.mcp.smart_llm_tools  # noqa: F401
from integration_hub_backend.mcp.smart_llm_tools._dispatch import _service_for
from integration_hub_backend.mcp.tools import TOOL_DEFINITIONS

WRAPPED = [
    "create_notification_rule",
    "datadog_query_logs",
    "drive_list",
    "elasticsearch_search",
    "gmail_list",
    "gmail_read",
    "gmail_reply",
    "gmail_send",
    "list_notification_event_types",
    "list_notification_rules",
    "outlook_list",
    "outlook_read",
    "outlook_reply",
    "outlook_send",
    "postgres_describe_table",
    "postgres_list_tables",
    "postgres_run_query",
    "stripe_get_customer",
    "stripe_list_invoices",
]


@pytest.mark.parametrize("name", WRAPPED)
def test_each_tool_is_registered_as_an_action_tool(name: str) -> None:
    meta = get_tool_meta(name)
    assert meta is not None, name
    assert issubclass(meta.cls, ActionTool)


@pytest.mark.parametrize("kind", sorted({info["service"] for info in TOOL_DEFINITIONS.values()}))
def test_dispatch_builds_every_service_tool_definitions_names(kind: str) -> None:
    assert _service_for(kind, MagicMock()) is not None

"""integration-hub's tools as smart-llm action tools.

Wraps every operation in ``mcp/tools.TOOL_DEFINITIONS`` as a smart-llm
:class:`~smart_llm.base.ActionTool` and registers it, so the tools the MCP
server exposes are also first-class skills for the agent runtime, the AI admin
UI and the workflow builder's TOOLS palette.

This lives in integration-hub, not smart-llm: the tools call integration-hub's
services in-process, and a shared library must not import the service built on
it (roadmap 2.9). Import this package once at startup — next to
``from smart_llm import builtins`` — to register them.
"""

# Import order matches mcp/tools.TOOL_DEFINITIONS for easy auditing.
from . import (
    drive,  # noqa: F401          — 1 tool
    gmail,  # noqa: F401          — 4 tools
    notifications,  # noqa: F401  — 3 rule-builder tools
    observability,  # noqa: F401  — 2 tools
    outlook,  # noqa: F401        — 4 tools
    postgres,  # noqa: F401       — 3 tools
    stripe,  # noqa: F401         — 2 tools
)

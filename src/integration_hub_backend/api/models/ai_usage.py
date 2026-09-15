"""Phase-E4 — AIUsageEvent shim.

The ORM class is built by :func:`smart_llm.usage.make_usage_model`
against this host's declarative ``Base`` so the table sits in
integration-hub's metadata next to the agent/skill tables.
"""

from __future__ import annotations

from smart_llm.usage import make_usage_model

from integration_hub_backend.api.core.db import Base

AIUsageEvent = make_usage_model(Base)

__all__ = ["AIUsageEvent"]

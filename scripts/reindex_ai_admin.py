"""One-shot bulk reindex for the ``ai_admin_v1`` Elasticsearch index.

Use when:
- Bootstrapping a new ES cluster (initial population)
- Recovering from data loss / index corruption
- The index hooks in agents/skills routers ever skipped a write
  (ES temporarily unreachable — index returns 0 ok)

Idempotent — every doc is upserted by deterministic
``{type}:{id}`` document ID.

Run inside the integration-hub-api container:

    docker exec sentinelbuild-integration-hub-api-1 \\
        python scripts/reindex_ai_admin.py
"""

from __future__ import annotations

import asyncio
import logging
import sys
from typing import Any

from smart_llm.api import ai_search_index
from smart_llm.registry import list_tools
from sqlalchemy import select

from integration_hub_backend.api.core.db import AsyncSessionLocal
from integration_hub_backend.api.models.ai_agent import AIAgentConfig, AISkill

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("reindex_ai_admin")


async def main() -> int:
    ok = await ai_search_index.ensure_index()
    if not ok:
        log.error("ES unreachable — aborting reindex")
        return 1

    docs: list[tuple[str, str, dict[str, Any]]] = []

    async with AsyncSessionLocal() as session:
        agents = (await session.execute(select(AIAgentConfig))).scalars().all()
        log.info("Reindexing %d agents", len(agents))
        for a in agents:
            docs.append(("agent", str(a.id), ai_search_index.agent_to_doc(a)))

        skills = (await session.execute(select(AISkill))).scalars().all()
        log.info("Reindexing %d skills", len(skills))
        for s in skills:
            docs.append(("skill", str(s.id), ai_search_index.skill_to_doc(s)))

    tools = list_tools()
    log.info("Reindexing %d tools", len(tools))
    for name, meta in tools.items():
        docs.append(("tool", name, ai_search_index.tool_to_doc(name, meta)))

    indexed = await ai_search_index.bulk_index(docs)
    log.info("Done. %d / %d docs indexed into %s", indexed, len(docs), ai_search_index.INDEX_NAME)
    return 0 if indexed == len(docs) else 2


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))

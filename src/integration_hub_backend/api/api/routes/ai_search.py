"""Phase H — Natural-language search across registered entities.

``POST /api/integration-hub/v1/ai-search/{entity}`` translates a NL
query into a tenant-scoped ``SELECT`` via the seeded "Database
Inspector" agent and returns the rows.

Auth: ``CompanyAdminDep`` for now (matches ``/ai-tools/run``). When
``/ai-tools/run`` widens to read-only callers, this endpoint should
follow the same pattern.
"""

from typing import Any

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field
from smart_llm.api import ai_search_index

from integration_hub_backend.api.api.deps import (
    CompanyAdminDep,
    CurrentUser,
    SessionDep,
)
from integration_hub_backend.api.services.ai_search_registry import (
    list_entities,
)
from integration_hub_backend.api.services.ai_search_service import (
    AiSearchValidationError,
    run_ai_search,
)

router = APIRouter(prefix="/ai-search", tags=["ai-search"])


class AiSearchRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=500)
    limit: int = Field(50, ge=1, le=200)


class AiSearchResponse(BaseModel):
    rows: list[dict[str, Any]]
    sql: str
    took_ms: int
    entity: str


@router.get("/entities", response_model=list[str])
async def get_searchable_entities() -> list[str]:
    """Frontend-discoverable list of entity names."""
    return list_entities()


@router.post("/{entity}", response_model=AiSearchResponse)
async def search_entity(
    entity: str,
    body: AiSearchRequest,
    session: SessionDep,
    current_user: CompanyAdminDep,
) -> AiSearchResponse:
    if current_user.company_id is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No company_id on caller token",
        )
    company_id = current_user.company_id

    try:
        result = await run_ai_search(
            session,
            entity_name=entity,
            company_id=company_id,
            query=body.query,
            limit=body.limit,
        )
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except AiSearchValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc
    except Exception as exc:  # pragma: no cover — surfaced as 502
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"AI search failed: {exc}",
        ) from exc

    return AiSearchResponse(
        rows=result.rows,
        sql=result.sql,
        took_ms=result.took_ms,
        entity=entity,
    )


# ── Phase M — AI Admin Elasticsearch search ─────────────────────────────────
#
# Distinct from Phase H above: this is a free-text search over the
# AI Admin "things you can configure" (agents + skills + tools)
# backed by an Elasticsearch index, not an NL→SQL pipeline. Used by
# the AI Admin UI to replace its in-memory client-side filter once
# the dataset grows past comfortable scan.


@router.get("/admin")
async def admin_search(
    current_user: CurrentUser,
    q: str = "",
    type: str | None = None,
    limit: int = 25,
) -> dict[str, Any]:
    """Free-text search over indexed agents / skills / tools.

    - ``q`` — query string. Empty → ``[]``.
    - ``type`` — optional filter: ``agent`` | ``skill`` | ``tool``.
    - Cross-tenant for ``system_admin``/``platform_admin``;
      per-tenant otherwise (plus globally-scoped rows like tools).
    - Falls back to ``[]`` when ES is unreachable so the UI degrades
      gracefully to its in-memory filter.
    """
    role = getattr(current_user, "role", None)
    if role in ("system_admin", "platform_admin"):
        company_id = None
    else:
        cid = getattr(current_user, "company_id", None)
        company_id = str(cid) if cid else None

    rows = await ai_search_index.search(
        q,
        company_id=company_id,
        type_filter=type,
        limit=max(1, min(int(limit), 100)),
    )
    return {"results": rows, "count": len(rows)}

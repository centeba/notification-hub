"""Internal route — seed default AI skills/agents for one company.

Called by user-master's ``crud.create_company`` (or any sibling that
provisions tenants) right after a company row is committed. Re-runnable
and idempotent — see :func:`ai_seed.seed_ai_for_company`.

Auth: ``Authorization: Bearer ${INTERNAL_SERVICE_SECRET}``. Not
reachable through the external nginx ingress — only the docker
service-to-service network.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field

from integration_hub_backend.api.api.deps import InternalServiceDep, SessionDep
from integration_hub_backend.api.services.ai_seed import seed_ai_for_company

router = APIRouter(prefix="/internal", tags=["internal"])


class SeedRequest(BaseModel):
    company_id: uuid.UUID = Field(..., description="UUID of the freshly-created company.")


class SeedResponse(BaseModel):
    company_id: uuid.UUID
    skills_seeded: int
    agents_seeded: int
    links_seeded: int


@router.post(
    "/companies/seed-ai",
    response_model=SeedResponse,
    status_code=status.HTTP_200_OK,
)
async def seed_company_ai(
    body: SeedRequest,
    session: SessionDep,
    _internal: InternalServiceDep,
) -> SeedResponse:
    """Seed default builtin skills + agents for ``body.company_id``."""
    try:
        report = await seed_ai_for_company(session, body.company_id)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"AI seed failed: {exc}",
        )
    return SeedResponse(company_id=body.company_id, **report)

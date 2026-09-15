"""Mailchimp integration — manage list members."""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel

from integration_hub_backend.api.api.deps import ApiKeyDep, SessionDep
from integration_hub_backend.api.services.marketing_service import MarketingService

router = APIRouter(prefix="/mailchimp", tags=["integrations"])


class MailchimpMemberRequest(BaseModel):
    credential_id: uuid.UUID
    operation: str  # subscribe | update | archive | get_member | add_tag
    list_id: str
    email: str
    merge_fields: dict[str, Any] = {}
    tags: list[str] = []


@router.post("/member")
async def mailchimp_member(
    body: MailchimpMemberRequest, db: SessionDep, api_key: ApiKeyDep
) -> dict[str, Any]:
    api_key.require_scope("integrations:mailchimp")
    service = MarketingService(db)
    return await service.mailchimp_member_operation(
        company_id=api_key.company_id,
        credential_id=body.credential_id,
        operation=body.operation,
        list_id=body.list_id,
        email=body.email,
        merge_fields=body.merge_fields,
        tags=body.tags,
    )

"""Gmail integration — send and read via Gmail API (OAuth2 access token)."""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel

from integration_hub_backend.api.api.deps import ApiKeyDep, SessionDep
from integration_hub_backend.api.services.email_service import EmailService

router = APIRouter(prefix="/gmail", tags=["integrations"])


class GmailSendRequest(BaseModel):
    credential_id: uuid.UUID
    to: str
    subject: str
    body: str = ""
    body_html: str = ""
    cc: str = ""
    bcc: str = ""


class GmailReadRequest(BaseModel):
    credential_id: uuid.UUID
    query: str = "is:unread"
    max_results: int = 10
    mark_as_read: bool = False


@router.post("/send")
async def gmail_send(body: GmailSendRequest, db: SessionDep, api_key: ApiKeyDep) -> dict[str, Any]:
    api_key.require_scope("integrations:gmail")
    service = EmailService(db)
    return await service.gmail_send(
        company_id=api_key.company_id,
        credential_id=body.credential_id,
        to=body.to,
        subject=body.subject,
        body=body.body,
        body_html=body.body_html,
        cc=body.cc,
        bcc=body.bcc,
    )


@router.post("/read")
async def gmail_read(body: GmailReadRequest, db: SessionDep, api_key: ApiKeyDep) -> dict[str, Any]:
    api_key.require_scope("integrations:gmail")
    service = EmailService(db)
    result = await service.gmail_list_unread(
        company_id=api_key.company_id,
        credential_id=body.credential_id,
        query=body.query,
        max_results=body.max_results,
    )
    # Service now returns ``{messages, next_page_token}`` (Phase F1.5
    # pagination). Surface the cursor so callers can paginate.
    messages = result["messages"]
    return {
        "messages": messages,
        "count": len(messages),
        "next_page_token": result.get("next_page_token"),
    }

"""Outlook integration — send and read via Microsoft Graph API (OAuth2)."""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel

from integration_hub_backend.api.api.deps import ApiKeyDep, SessionDep
from integration_hub_backend.api.services.email_service import EmailService

router = APIRouter(prefix="/outlook", tags=["integrations"])


class OutlookSendRequest(BaseModel):
    credential_id: uuid.UUID
    to: str | list[str]
    subject: str
    body: str = ""
    body_html: str = ""
    cc: str | list[str] = ""
    save_to_sent: bool = True


class OutlookReadRequest(BaseModel):
    credential_id: uuid.UUID
    folder: str = "Inbox"
    filter_query: str = "isRead eq false"
    max_results: int = 10
    mark_as_read: bool = False


@router.post("/send")
async def outlook_send(
    body: OutlookSendRequest, db: SessionDep, api_key: ApiKeyDep
) -> dict[str, Any]:
    api_key.require_scope("integrations:outlook")
    service = EmailService(db)
    return await service.outlook_send(
        company_id=api_key.company_id,
        credential_id=body.credential_id,
        to=body.to,
        subject=body.subject,
        body=body.body,
        body_html=body.body_html,
        cc=body.cc,
        save_to_sent=body.save_to_sent,
    )


@router.post("/read")
async def outlook_read(
    body: OutlookReadRequest, db: SessionDep, api_key: ApiKeyDep
) -> dict[str, Any]:
    api_key.require_scope("integrations:outlook")
    service = EmailService(db)
    result = await service.outlook_list_messages(
        company_id=api_key.company_id,
        credential_id=body.credential_id,
        folder=body.folder,
        filter_query=body.filter_query,
        max_results=body.max_results,
        mark_as_read=body.mark_as_read,
    )
    messages = result["messages"]
    return {
        "messages": messages,
        "count": len(messages),
        "next_page_token": result.get("next_page_token"),
    }

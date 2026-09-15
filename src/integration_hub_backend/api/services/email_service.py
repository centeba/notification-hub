"""Service for Email integrations (Gmail, Outlook, SMTP)."""

import base64
import uuid
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Any

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from integration_hub_backend.api.crud.integration_credentials import get_credential, get_decrypted


class EmailService:
    def __init__(self, db: AsyncSession):
        self.db = db

    def _addr_list(self, addresses: str | list[str]) -> list[dict[str, Any]]:
        if isinstance(addresses, str):
            addresses = [addresses] if addresses else []
        return [{"emailAddress": {"address": a}} for a in addresses if a]

    async def _get_auth_headers(
        self, credential_id: uuid.UUID, company_id: uuid.UUID
    ) -> dict[str, str]:
        cred = await get_credential(self.db, credential_id, company_id)
        if not cred:
            raise ValueError("Credential not found")
        token = get_decrypted(cred).get("access_token", "")
        return {"Authorization": f"Bearer {token}"}

    # ── Gmail ───────────────────────────────────────────────────────────────

    async def gmail_send(
        self,
        company_id: uuid.UUID,
        credential_id: uuid.UUID,
        to: str,
        subject: str,
        body: str = "",
        body_html: str = "",
        cc: str = "",
        bcc: str = "",
    ) -> dict[str, Any]:
        """Send an email via Gmail API."""
        headers = await self._get_auth_headers(credential_id, company_id)

        if body_html:
            msg: MIMEMultipart | MIMEText = MIMEMultipart("alternative")
            msg["Subject"] = subject
            msg["To"] = to
            if cc:
                msg["Cc"] = cc
            if bcc:
                msg["Bcc"] = bcc
            msg.attach(MIMEText(body, "plain"))
            msg.attach(MIMEText(body_html, "html"))
        else:
            msg = MIMEText(body, "plain")
            msg["Subject"] = subject
            msg["To"] = to
            if cc:
                msg["Cc"] = cc

        raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                "https://gmail.googleapis.com/gmail/v1/users/me/messages/send",
                headers=headers,
                json={"raw": raw},
            )
            resp.raise_for_status()
            result: dict[str, Any] = resp.json()
            return result

    async def gmail_list_unread(
        self,
        company_id: uuid.UUID,
        credential_id: uuid.UUID,
        query: str = "is:unread",
        max_results: int = 10,
        page_token: str | None = None,
    ) -> dict[str, Any]:
        """List unread messages from Gmail with cursor pagination.

        Return shape: ``{messages: [...], next_page_token: str | None}``.
        Pass the returned ``next_page_token`` back as ``page_token``
        to fetch the subsequent page; ``None`` means no further pages.
        """
        headers = await self._get_auth_headers(credential_id, company_id)
        _BASE = "https://gmail.googleapis.com/gmail/v1/users/me"

        params: dict[str, Any] = {"q": query, "maxResults": max_results}
        if page_token:
            params["pageToken"] = page_token

        async with httpx.AsyncClient(timeout=30) as client:
            list_resp = await client.get(
                f"{_BASE}/messages",
                headers=headers,
                params=params,
            )
            list_resp.raise_for_status()
            list_body = list_resp.json()
            msg_ids = [m["id"] for m in list_body.get("messages", [])]
            next_token = list_body.get("nextPageToken")

            messages = []
            for msg_id in msg_ids:
                detail_resp = await client.get(
                    f"{_BASE}/messages/{msg_id}", headers=headers, params={"format": "full"}
                )
                detail_resp.raise_for_status()
                detail = detail_resp.json()
                hmap = {
                    h["name"].lower(): h["value"]
                    for h in detail.get("payload", {}).get("headers", [])
                }
                body_plain = self._extract_gmail_body(detail.get("payload", {}))
                messages.append(
                    {
                        "id": msg_id,
                        "subject": hmap.get("subject", ""),
                        "from": hmap.get("from", ""),
                        "date": hmap.get("date", ""),
                        "snippet": detail.get("snippet", ""),
                        "body_plain": body_plain,
                    }
                )
            return {"messages": messages, "next_page_token": next_token}

    @staticmethod
    def _extract_gmail_body(payload: dict[str, Any]) -> str:
        """Decode the full plain-text body from a Gmail message payload."""
        # Single-part message
        if payload.get("mimeType") == "text/plain" and "body" in payload:
            data = payload["body"].get("data", "")
            if data:
                return base64.urlsafe_b64decode(data).decode("utf-8", errors="replace")

        # Multi-part: walk parts looking for text/plain
        for part in payload.get("parts", []):
            if part.get("mimeType") == "text/plain":
                data = part.get("body", {}).get("data", "")
                if data:
                    return base64.urlsafe_b64decode(data).decode("utf-8", errors="replace")
            # Nested multipart
            if part.get("parts"):
                result = EmailService._extract_gmail_body(part)
                if result:
                    return result

        return ""

    # ── Outlook ─────────────────────────────────────────────────────────────

    async def outlook_send(
        self,
        company_id: uuid.UUID,
        credential_id: uuid.UUID,
        to: str | list[str],
        subject: str,
        body: str = "",
        body_html: str = "",
        cc: str | list[str] = "",
        save_to_sent: bool = True,
    ) -> dict[str, Any]:
        """Send an email via Microsoft Graph API."""
        headers = await self._get_auth_headers(credential_id, company_id)
        headers["Content-Type"] = "application/json"

        content_type = "html" if body_html else "text"
        content = body_html if body_html else body

        message: dict[str, Any] = {
            "subject": subject,
            "body": {"contentType": content_type, "content": content},
            "toRecipients": self._addr_list(to),
        }
        if cc:
            message["ccRecipients"] = self._addr_list(cc)

        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                "https://graph.microsoft.com/v1.0/me/sendMail",
                headers=headers,
                json={"message": message, "saveToSentItems": save_to_sent},
            )
            resp.raise_for_status()
        return {"status": "sent", "subject": subject}

    async def outlook_list_messages(
        self,
        company_id: uuid.UUID,
        credential_id: uuid.UUID,
        folder: str = "Inbox",
        filter_query: str = "isRead eq false",
        max_results: int = 10,
        mark_as_read: bool = False,
        page_token: str | None = None,
    ) -> dict[str, Any]:
        """List messages from Outlook using Microsoft Graph.

        Return shape: ``{messages: [...], next_page_token: str | None}``.
        ``page_token`` is the full ``@odata.nextLink`` URL returned in
        a prior response — Microsoft Graph paginates by opaque URL, not
        cursor token.
        """
        headers = await self._get_auth_headers(credential_id, company_id)
        headers["Content-Type"] = "application/json"

        query_params: dict[str, Any] = {
            "$top": max_results,
            "$select": "id,subject,from,receivedDateTime,bodyPreview,body,isRead",
            "$orderby": "receivedDateTime desc",
        }
        if filter_query:
            query_params["$filter"] = filter_query

        async with httpx.AsyncClient(timeout=30) as client:
            if page_token:
                # Subsequent page — Graph returned the full URL with
                # all params baked in; don't add our own.
                resp = await client.get(page_token, headers=headers)
            else:
                resp = await client.get(
                    f"https://graph.microsoft.com/v1.0/me/mailFolders/{folder}/messages",
                    headers=headers,
                    params=query_params,
                )
            resp.raise_for_status()
            body = resp.json()
            messages = body.get("value", [])
            next_link = body.get("@odata.nextLink")

            if mark_as_read:
                for m in messages:
                    if not m.get("isRead"):
                        await client.patch(
                            f"https://graph.microsoft.com/v1.0/me/messages/{m['id']}",
                            headers=headers,
                            json={"isRead": True},
                        )

            shaped = [
                {
                    "id": m["id"],
                    "subject": m.get("subject", ""),
                    "from": m.get("from", {}).get("emailAddress", {}).get("address", ""),
                    "date": m.get("receivedDateTime", ""),
                    "preview": m.get("bodyPreview", ""),
                    "body_content": m.get("body", {}).get("content", ""),
                    "is_read": m.get("isRead", False),
                }
                for m in messages
            ]
            return {"messages": shaped, "next_page_token": next_link}

    # ── Gmail read / reply ──────────────────────────────────────────────────

    async def gmail_get_message(
        self,
        company_id: uuid.UUID,
        credential_id: uuid.UUID,
        message_id: str,
    ) -> dict[str, Any]:
        """Fetch a single Gmail message by ID, returning headers + full body."""
        headers = await self._get_auth_headers(credential_id, company_id)
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(
                f"https://gmail.googleapis.com/gmail/v1/users/me/messages/{message_id}",
                headers=headers,
                params={"format": "full"},
            )
            resp.raise_for_status()
            detail = resp.json()
        hmap = {h["name"].lower(): h["value"] for h in detail.get("payload", {}).get("headers", [])}
        return {
            "id": message_id,
            "thread_id": detail.get("threadId", ""),
            "subject": hmap.get("subject", ""),
            "from": hmap.get("from", ""),
            "to": hmap.get("to", ""),
            "date": hmap.get("date", ""),
            "snippet": detail.get("snippet", ""),
            "body_plain": self._extract_gmail_body(detail.get("payload", {})),
        }

    async def gmail_reply(
        self,
        company_id: uuid.UUID,
        credential_id: uuid.UUID,
        thread_id: str,
        to: str,
        subject: str,
        body: str = "",
        body_html: str = "",
    ) -> dict[str, Any]:
        """Reply to an existing Gmail thread."""
        headers = await self._get_auth_headers(credential_id, company_id)
        reply_subject = subject if subject.lower().startswith("re:") else f"Re: {subject}"

        if body_html:
            msg: MIMEMultipart | MIMEText = MIMEMultipart("alternative")
            msg["Subject"] = reply_subject
            msg["To"] = to
            msg.attach(MIMEText(body, "plain"))
            msg.attach(MIMEText(body_html, "html"))
        else:
            msg = MIMEText(body, "plain")
            msg["Subject"] = reply_subject
            msg["To"] = to

        raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                "https://gmail.googleapis.com/gmail/v1/users/me/messages/send",
                headers=headers,
                json={"raw": raw, "threadId": thread_id},
            )
            resp.raise_for_status()
            result: dict[str, Any] = resp.json()
            return result

    # ── Outlook read / reply ────────────────────────────────────────────────

    async def outlook_get_message(
        self,
        company_id: uuid.UUID,
        credential_id: uuid.UUID,
        message_id: str,
    ) -> dict[str, Any]:
        """Fetch a single Outlook message by ID via Microsoft Graph."""
        headers = await self._get_auth_headers(credential_id, company_id)
        headers["Content-Type"] = "application/json"
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(
                f"https://graph.microsoft.com/v1.0/me/messages/{message_id}",
                headers=headers,
                params={
                    "$select": "id,subject,from,toRecipients,receivedDateTime,body,bodyPreview,conversationId,isRead"
                },
            )
            resp.raise_for_status()
            m = resp.json()
        return {
            "id": m["id"],
            "conversation_id": m.get("conversationId", ""),
            "subject": m.get("subject", ""),
            "from": m.get("from", {}).get("emailAddress", {}).get("address", ""),
            "to": [r["emailAddress"]["address"] for r in m.get("toRecipients", [])],
            "date": m.get("receivedDateTime", ""),
            "preview": m.get("bodyPreview", ""),
            "body_content": m.get("body", {}).get("content", ""),
            "is_read": m.get("isRead", False),
        }

    async def outlook_reply(
        self,
        company_id: uuid.UUID,
        credential_id: uuid.UUID,
        message_id: str,
        body: str = "",
        body_html: str = "",
    ) -> dict[str, Any]:
        """Reply to an Outlook message in-place via Microsoft Graph."""
        headers = await self._get_auth_headers(credential_id, company_id)
        headers["Content-Type"] = "application/json"
        content_type = "html" if body_html else "text"
        content = body_html if body_html else body
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                f"https://graph.microsoft.com/v1.0/me/messages/{message_id}/reply",
                headers=headers,
                json={
                    "comment": content,
                    "message": {"body": {"contentType": content_type, "content": content}},
                },
            )
            resp.raise_for_status()
        return {"status": "replied", "message_id": message_id}

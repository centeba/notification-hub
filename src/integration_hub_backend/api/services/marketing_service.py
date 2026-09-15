"""Service for Marketing integrations (Mailchimp)."""

import hashlib
import uuid
from typing import Any

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from integration_hub_backend.api.crud.integration_credentials import get_credential, get_decrypted


class MarketingService:
    def __init__(self, db: AsyncSession):
        self.db = db

    def _member_hash(self, email: str) -> str:
        # Mailchimp identifies list members by the MD5 of the lowercased email —
        # a required part of their API contract, not a security hash.
        return hashlib.md5(email.strip().lower().encode(), usedforsecurity=False).hexdigest()

    async def _get_auth(
        self, credential_id: uuid.UUID, company_id: uuid.UUID
    ) -> tuple[str, str, str]:
        """Returns (auth_user, api_key, server_prefix)."""
        cred = await get_credential(self.db, credential_id, company_id)
        if not cred:
            raise ValueError("Credential not found")
        api_key = get_decrypted(cred).get("api_key", "")
        server = api_key.split("-")[-1] if "-" in api_key else "us1"
        return ("anystring", api_key, server)

    # ── Mailchimp ───────────────────────────────────────────────────────────

    async def mailchimp_member_operation(
        self,
        company_id: uuid.UUID,
        credential_id: uuid.UUID,
        operation: str,
        list_id: str,
        email: str,
        merge_fields: dict[str, Any] | None = None,
        tags: list[str] | None = None,
    ) -> dict[str, Any]:
        """Perform a member-level operation in Mailchimp."""
        auth_user, api_key, server = await self._get_auth(credential_id, company_id)
        base = f"https://{server}.api.mailchimp.com/3.0"
        auth = (auth_user, api_key)
        member_hash = self._member_hash(email)

        async with httpx.AsyncClient(timeout=30) as client:
            match operation:
                case "subscribe":
                    resp = await client.put(
                        f"{base}/lists/{list_id}/members/{member_hash}",
                        auth=auth,
                        json={
                            "email_address": email,
                            "status_if_new": "subscribed",
                            "status": "subscribed",
                            "merge_fields": merge_fields or {},
                        },
                    )
                case "update":
                    resp = await client.patch(
                        f"{base}/lists/{list_id}/members/{member_hash}",
                        auth=auth,
                        json={"merge_fields": merge_fields or {}},
                    )
                case "archive":
                    resp = await client.delete(
                        f"{base}/lists/{list_id}/members/{member_hash}", auth=auth
                    )
                    resp.raise_for_status()
                    return {"status": "archived", "email": email}
                case "get_member":
                    resp = await client.get(
                        f"{base}/lists/{list_id}/members/{member_hash}", auth=auth
                    )
                case "add_tag":
                    resp = await client.post(
                        f"{base}/lists/{list_id}/members/{member_hash}/tags",
                        auth=auth,
                        json={"tags": [{"name": t, "status": "active"} for t in (tags or [])]},
                    )
                    resp.raise_for_status()
                    return {"status": "tags_added", "tags": tags}
                case _:
                    raise ValueError(f"Unknown operation: {operation}")

            resp.raise_for_status()
            result: dict[str, Any] = resp.json()
            return result

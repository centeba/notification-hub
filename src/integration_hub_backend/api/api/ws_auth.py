"""WebSocket JWT auth — shared decoder.

Browser ``WebSocket`` clients can't send custom ``Authorization``
headers, so every WS route in this service accepts the JWT in a query
string (``?token=...``) and decodes it manually. Two endpoints rely on
this today:

- the Phase E3 AI-streaming proxy at ``/api/v1/ws/...`` (defined in
  ``main.py``); and
- the Phase 5.1 subscription bus at ``/api/v1/subscribe/{topic}``
  (defined in ``routes/subscription_bus.py``).

Both share the same decode logic so the auth surface stays consistent.

The previous home of this function was inline in ``main.py``; lifting it
into its own module so any future WS route can import it without
pulling the whole API entrypoint into scope.
"""

from __future__ import annotations

import uuid as _uuid

from smart_llm.platform_auth import decode_platform_token

from integration_hub_backend.api.api.deps import CurrentUserPayload
from integration_hub_backend.api.core.config import settings as _settings


async def resolve_token_for_stream(token: str) -> CurrentUserPayload | None:
    """Decode a JWT minted by user-master.

    Returns the :class:`CurrentUserPayload` on success, or ``None`` on
    any decode/validation failure — callers should treat ``None`` as
    "close the socket with policy-violation (1008)".

    Two cases that intentionally return ``None`` rather than raising:

    - signature / expiry / shape error from PyJWT;
    - ``scope == "pre_2fa"`` — these tokens shouldn't unlock streaming
      surfaces; the user must complete TOTP first.

    ``company_id`` is optional in the payload (platform admins don't
    have one); the returned ``CurrentUserPayload.company_id`` is
    ``None`` in that case and callers must decide what that means
    (e.g. allow subscriptions to any tenant's topic, or reject).
    """
    try:
        payload = decode_platform_token(token, _settings.SECRET_KEY, require=["sub", "exp"])
    except Exception:
        return None
    if payload.get("scope") == "pre_2fa":
        return None
    company_id_raw = payload.get("company_id")
    return CurrentUserPayload(
        user_id=_uuid.UUID(payload["sub"]),
        company_id=_uuid.UUID(company_id_raw) if company_id_raw else None,
        role=payload.get("role", "user"),
        email=payload.get("email", ""),
    )

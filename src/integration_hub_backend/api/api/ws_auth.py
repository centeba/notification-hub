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

from fastapi import HTTPException
from smart_llm.current_user import authenticate

from integration_hub_backend.api.api.deps import CurrentUserPayload, _stamp_tenant


async def resolve_token_for_stream(token: str) -> CurrentUserPayload | None:
    """Verify a JWT minted by user-master for a WebSocket / stream.

    Returns the user on success, or ``None`` on any failure (bad, expired,
    revoked, non-``full`` scope, bad claims) — callers should treat ``None`` as
    "close the socket with policy-violation (1008)". Same shared contract as
    ``get_current_user``; ``company_id`` is ``None`` for a company-less token.
    """
    try:
        user = await authenticate(token)
    except HTTPException:
        return None
    # RLS: the stream / subscription handlers open their own DB sessions after
    # this returns, so stamp the tenant here exactly as get_current_user does
    # (org, or bypass for platform admins) — unstamped they would see no rows.
    _stamp_tenant(user)
    return user

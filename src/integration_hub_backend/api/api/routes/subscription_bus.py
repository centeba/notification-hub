"""Phase 5.1 — generic WebSocket subscription bus.

Browser clients subscribe to a public **topic name** and receive JSON
messages until they disconnect. The bus maps topics onto internal
Redis pub/sub channels via :data:`TOPIC_TO_REDIS_RULES`, so the
public surface stays explicit (the bus only allows subscriptions to
topics whose shape matches a rule).

Wire protocol (matches the Phase E3 AI-streaming proxy at
``/api/v1/ws/ai-agents/{id}/stream`` so the chassis can reuse one
adapter shape for both):

1. Client opens ``WS /api/v1/subscribe/{topic}``.
2. Server accepts and waits for a first JSON message
   ``{"token": "<jwt>"}`` (browsers cannot send custom
   ``Authorization`` headers on a WebSocket).
3. Server validates the JWT via
   :func:`integration_hub_backend.api.api.ws_auth.resolve_token_for_stream`.
4. Server checks the topic ACL (caller's tenant must match the
   topic's tenant claim, with platform admins bypassing).
5. Server resolves the topic onto a Redis pub/sub channel and
   bridges the stream. Each Redis message is forwarded as a WS text
   frame verbatim (JSON-encoded string the client decodes itself).
6. Disconnect → unsubscribe from Redis, close the WS.

Today's only mapping covers ``org.{org_id}.execution.{execution_id}``
which targets the existing ``exec:logs:{execution_id}`` channel
mit-stack already publishes execution status updates to. Future event
types add rules to :data:`TOPIC_TO_REDIS_RULES`; no service needs to
republish for the bus to know about them.

Documented in ``documents/services/integration-hub/architecture.md``
and ``documents/platform/web-builder-roadmap.md`` (Phase 8).
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import re
import uuid as _uuid
from collections.abc import Callable

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from integration_hub_backend.api.api.deps import CurrentUserPayload
from integration_hub_backend.api.api.ws_auth import resolve_token_for_stream
from integration_hub_backend.api.core.subscription_hub import get_subscription_hub

router = APIRouter(tags=["subscription-bus"])


# ── Topic ↔ Redis channel mapping ────────────────────────────────────────────
# Each rule pairs a regex over the public topic name with a function
# that, given the regex Match, returns the internal Redis channel name.
# Adding a new event type to the bus is a one-line addition here plus
# (if the channel doesn't exist yet) a `redis.publish(...)` call in
# the originating service.

_TopicRule = tuple[re.Pattern[str], Callable[[re.Match[str]], str]]

TOPIC_TO_REDIS_RULES: list[_TopicRule] = [
    # mit-stack publishes JSON updates here from
    # services/mit-stack/backend/temporal/activities/state_activity.py
    # whenever a workflow execution transitions state. The channel
    # format ``exec:logs:{id}`` is the canonical contract documented in
    # ``sentinelbuild_sdk.channels.exec_logs_channel`` — if it changes,
    # also update mit-stack ``shared/redis_client.py::RedisKeys.exec_logs``.
    (
        re.compile(r"^org\.([^.]+)\.execution\.([^.]+)$"),
        lambda m: f"exec:logs:{m.group(2)}",
    ),
    # AI budget cap alerts (Phase F). Publishers:
    #   * ``smart_llm.usage._emit_budget_exhausted_alert`` — fired on
    #     the first cap trip per (company, month) from
    #     ``assert_llm_allowed_for_tenant``. Throttled by Redis
    #     SET-NX so a tenant doesn't spam new alerts on every blocked
    #     call.
    # ACL: the existing ``_topic_acl_ok`` already restricts
    # ``org.{X}.*`` to JWTs whose company_id == X, so cross-tenant
    # subscribe is denied without any extra check here.
    (
        re.compile(r"^org\.([^.]+)\.alert\.budget_exhausted$"),
        lambda m: f"alert:budget_exhausted:{m.group(1)}",
    ),
    # Future event types land here. Examples we expect to add as
    # services start publishing:
    #   org.{X}.envelope.{Y}   → esign:audit:{Y}   (esignature)
    #   org.{X}.document.{Y}   → vault:ingest:{Y}  (doc-vault)
    #   app.{N}.{entity}.{id}  → custom per vertical app
]


def _resolve_redis_channel(topic: str) -> str | None:
    """Resolve a public topic to an internal Redis channel, or None."""
    for pat, fn in TOPIC_TO_REDIS_RULES:
        m = pat.match(topic)
        if m is not None:
            return fn(m)
    return None


def _topic_acl_ok(topic: str, user: CurrentUserPayload) -> bool:
    """Confirm the user is allowed to subscribe to ``topic``.

    Rules:

    - Platform admins bypass every check.
    - ``org.{X}.*`` requires the caller's JWT ``company_id`` to equal
      ``X``. Tokens without ``company_id`` (e.g. the first superuser)
      cannot subscribe to org-scoped topics — they have no tenant to
      bind to.
    - Anything else is default-denied. ``app.{X}.*`` will land here
      once the first vertical app needs it; the check will look up
      ``app_id ∈ company.enabled_packs`` via user-master.
    """
    if user.role in ("system_admin", "platform_admin"):
        return True
    org_match = re.match(r"^org\.([^.]+)\.", topic)
    if org_match is not None:
        try:
            target_org = _uuid.UUID(org_match.group(1))
        except ValueError:
            return False
        return user.company_id == target_org
    # TODO(phase-6): app.{app_id}.* — enabled_packs lookup, cache for
    # the connection's lifetime. Default-deny until implemented.
    return False


@router.websocket("/subscribe/{topic:path}")
async def subscribe(websocket: WebSocket, topic: str) -> None:
    await websocket.accept()
    try:
        init = await websocket.receive_json()
    except (WebSocketDisconnect, json.JSONDecodeError):
        await websocket.close(code=1003)
        return

    token = init.get("token") if isinstance(init, dict) else None
    if not token:
        await websocket.send_json({"error": "missing token"})
        await websocket.close(code=1008)
        return

    user = await resolve_token_for_stream(token)
    if user is None:
        await websocket.send_json({"error": "invalid token"})
        await websocket.close(code=1008)
        return

    if not _topic_acl_ok(topic, user):
        await websocket.send_json({"error": "forbidden topic"})
        await websocket.close(code=1008)
        return

    channel = _resolve_redis_channel(topic)
    if channel is None:
        await websocket.send_json({"error": "unknown topic"})
        await websocket.close(code=1003)
        return

    # Subscribe through the shared fan-out hub: one process-wide Redis pubsub
    # connection serves every WS client, so socket count no longer maps 1:1
    # onto the (bounded) Redis connection pool.
    hub = get_subscription_hub()
    sub = await hub.subscribe(channel)
    try:
        # Confirm subscription so the client can clear any "connecting"
        # spinner. Topic is echoed so the client can sanity-check
        # what the server resolved it to without leaking the internal
        # Redis channel name.
        await websocket.send_json({"event": "subscribed", "topic": topic})

        async def _pump() -> None:
            # Hub queue → WS. Frames are already JSON-encoded strings.
            while True:
                await websocket.send_text(await sub.queue.get())

        async def _watch_disconnect() -> None:
            # Detect client disconnect even while idle (no messages flowing):
            # ``receive`` raises WebSocketDisconnect on close. Without this the
            # subscriber would linger until the next Redis message failed to
            # send. Any further client frame also ends the stream.
            while True:
                await websocket.receive()

        pump = asyncio.create_task(_pump())
        watch = asyncio.create_task(_watch_disconnect())
        try:
            await asyncio.wait({pump, watch}, return_when=asyncio.FIRST_COMPLETED)
        finally:
            for task in (pump, watch):
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError, Exception):
                    await task
    except WebSocketDisconnect:
        pass
    except asyncio.CancelledError:
        # Server-side cancellation (shutdown, etc.). Let the close path run.
        pass
    finally:
        await hub.unsubscribe(sub)
        try:
            await websocket.close()
        except Exception:
            pass

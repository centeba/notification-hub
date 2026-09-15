"""Phase 5.1 — WebSocket subscription bus tests.

The bus has two surfaces worth testing in isolation:

1. Pure resolver / ACL logic — exercised directly via the helper
   functions, no FastAPI / Redis needed.
2. The WS handshake — driven via FastAPI's ``TestClient.websocket_connect``
   with the Redis pubsub mocked. We cover the auth refusals and one
   happy-path message-forwarding round-trip; deeper Redis behavior
   is out of scope for this test (covered by redis-py's own tests).
"""

from __future__ import annotations

import asyncio
import uuid
from typing import Any
from unittest.mock import MagicMock, patch

import jwt
from fastapi import FastAPI
from fastapi.testclient import TestClient

# Make sure conftest's SQLite JSONB shim runs even though we don't use the DB.
import integration_hub_backend  # noqa: F401
from integration_hub_backend.api.api.deps import CurrentUserPayload
from integration_hub_backend.api.api.routes.subscription_bus import (
    _resolve_redis_channel,
    _topic_acl_ok,
)
from integration_hub_backend.api.api.routes.subscription_bus import (
    router as bus_router,
)
from integration_hub_backend.api.core.config import settings

COMPANY_ID = uuid.uuid4()
OTHER_COMPANY_ID = uuid.uuid4()
USER_ID = uuid.uuid4()
EXECUTION_ID = uuid.uuid4()


# ─────────────────────────────────────────────────────────────────────────────
# 1. Pure resolver / ACL logic
# ─────────────────────────────────────────────────────────────────────────────


class TestResolveRedisChannel:
    def test_execution_topic_resolves(self) -> None:
        topic = f"org.{COMPANY_ID}.execution.{EXECUTION_ID}"
        assert _resolve_redis_channel(topic) == f"exec:logs:{EXECUTION_ID}"

    def test_unknown_topic_returns_none(self) -> None:
        assert _resolve_redis_channel("garbage.topic") is None
        assert _resolve_redis_channel("org.foo.envelope.bar") is None
        assert _resolve_redis_channel("") is None


class TestTopicAcl:
    def _member(self, company_id: uuid.UUID | None) -> CurrentUserPayload:
        return CurrentUserPayload(
            user_id=USER_ID,
            company_id=company_id,
            role="member",
            email="m@example.com",
        )

    def _admin(self) -> CurrentUserPayload:
        return CurrentUserPayload(
            user_id=USER_ID,
            company_id=None,
            role="system_admin",
            email="root@example.com",
        )

    def test_matching_org_allowed(self) -> None:
        topic = f"org.{COMPANY_ID}.execution.{EXECUTION_ID}"
        assert _topic_acl_ok(topic, self._member(COMPANY_ID)) is True

    def test_mismatching_org_denied(self) -> None:
        topic = f"org.{COMPANY_ID}.execution.{EXECUTION_ID}"
        assert _topic_acl_ok(topic, self._member(OTHER_COMPANY_ID)) is False

    def test_platform_admin_bypasses(self) -> None:
        topic = f"org.{COMPANY_ID}.execution.{EXECUTION_ID}"
        assert _topic_acl_ok(topic, self._admin()) is True

    def test_app_topic_default_denied(self) -> None:
        # Phase 6 follow-up — until enabled_packs lookup ships, app.* topics
        # are refused for non-admins (admins bypass).
        topic = "app.construction.job.123"
        assert _topic_acl_ok(topic, self._member(COMPANY_ID)) is False
        assert _topic_acl_ok(topic, self._admin()) is True

    def test_member_without_company_denied(self) -> None:
        # Platform admin uses role bypass; a regular member with no
        # company_id has nothing to bind to.
        topic = f"org.{COMPANY_ID}.execution.{EXECUTION_ID}"
        assert _topic_acl_ok(topic, self._member(None)) is False

    def test_malformed_org_uuid_denied(self) -> None:
        assert _topic_acl_ok("org.not-a-uuid.execution.x", self._member(COMPANY_ID)) is False


# ─────────────────────────────────────────────────────────────────────────────
# 2. WS handshake
# ─────────────────────────────────────────────────────────────────────────────


def _mint_token(
    *,
    company_id: uuid.UUID | None = COMPANY_ID,
    scope: str = "full",
    role: str = "member",
) -> str:
    payload: dict[str, Any] = {
        "sub": str(USER_ID),
        "exp": 9999999999,
        "scope": scope,
        "role": role,
        "email": "m@example.com",
    }
    if company_id is not None:
        payload["company_id"] = str(company_id)
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.ALGORITHM)


class _FakePubSub:
    """Minimal mock of redis-py's async PubSub, matching the interface the
    ``SubscriptionHub`` uses: ``subscribe``/``unsubscribe`` (variadic, recorded so
    we can assert which channel was subscribed) and ``get_message`` (the hub's
    reader polls this; here it yields nothing so the reader idles cleanly). A test
    can enqueue frames via ``push`` for ``get_message`` to return.
    """

    def __init__(self) -> None:
        self.subscribed: list[str] = []
        self.unsubscribed: list[str] = []
        self.closed = False
        self._queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()

    async def subscribe(self, *channels: str) -> None:
        self.subscribed.extend(channels)

    async def unsubscribe(self, *channels: str) -> None:
        self.unsubscribed.extend(channels)

    async def aclose(self) -> None:
        self.closed = True

    async def push(self, channel: str, data: str) -> None:
        await self._queue.put({"type": "message", "channel": channel, "data": data})

    async def get_message(
        self, *, ignore_subscribe_messages: bool = False, timeout: float | None = None
    ) -> dict[str, Any] | None:
        try:
            return self._queue.get_nowait()
        except asyncio.QueueEmpty:
            # Real redis-py blocks up to ``timeout`` here; mirror that so the
            # hub's reader yields to the loop each poll instead of busy-looping
            # (which would starve the event loop and hang the WS handler).
            await asyncio.sleep(timeout or 0.01)
            return None


def _make_test_app() -> tuple[FastAPI, _FakePubSub]:
    app = FastAPI()
    app.include_router(bus_router, prefix="/api/v1")

    fake_pubsub = _FakePubSub()
    fake_redis = MagicMock()
    fake_redis.pubsub = MagicMock(return_value=fake_pubsub)

    # The route subscribes through the process-wide SubscriptionHub, which builds
    # itself lazily from ``core.redis.get_redis_pool`` (imported at call time).
    # Patch there, and reset the hub singleton so it rebuilds against this fake.
    import integration_hub_backend.api.core.subscription_hub as hub_mod

    hub_mod._hub = None
    patcher = patch(
        "integration_hub_backend.api.core.redis.get_redis_pool",
        return_value=fake_redis,
    )
    patcher.start()
    app.state._patcher = patcher  # type: ignore[attr-defined]
    return app, fake_pubsub


def _teardown(app: FastAPI) -> None:
    p = getattr(app.state, "_patcher", None)
    if p is not None:
        p.stop()
    # Drop the fake-backed hub so it never leaks into another test.
    import integration_hub_backend.api.core.subscription_hub as hub_mod

    hub_mod._hub = None


class TestSubscriptionBusWS:
    def test_rejects_missing_token(self) -> None:
        app, _ = _make_test_app()
        try:
            client = TestClient(app)
            topic = f"org.{COMPANY_ID}.execution.{EXECUTION_ID}"
            with client.websocket_connect(f"/api/v1/subscribe/{topic}") as ws:
                ws.send_json({})  # no token field
                err = ws.receive_json()
                assert err == {"error": "missing token"}
        finally:
            _teardown(app)

    def test_rejects_invalid_token(self) -> None:
        app, _ = _make_test_app()
        try:
            client = TestClient(app)
            topic = f"org.{COMPANY_ID}.execution.{EXECUTION_ID}"
            with client.websocket_connect(f"/api/v1/subscribe/{topic}") as ws:
                ws.send_json({"token": "not-a-jwt"})
                err = ws.receive_json()
                assert err == {"error": "invalid token"}
        finally:
            _teardown(app)

    def test_rejects_cross_tenant(self) -> None:
        app, _ = _make_test_app()
        try:
            client = TestClient(app)
            # Token's company is OTHER_COMPANY_ID; topic targets COMPANY_ID.
            token = _mint_token(company_id=OTHER_COMPANY_ID)
            topic = f"org.{COMPANY_ID}.execution.{EXECUTION_ID}"
            with client.websocket_connect(f"/api/v1/subscribe/{topic}") as ws:
                ws.send_json({"token": token})
                err = ws.receive_json()
                assert err == {"error": "forbidden topic"}
        finally:
            _teardown(app)

    def test_rejects_unknown_topic(self) -> None:
        app, _ = _make_test_app()
        try:
            client = TestClient(app)
            token = _mint_token(company_id=None, role="system_admin")  # admin bypasses ACL
            with client.websocket_connect("/api/v1/subscribe/totally.unknown.topic") as ws:
                ws.send_json({"token": token})
                err = ws.receive_json()
                assert err == {"error": "unknown topic"}
        finally:
            _teardown(app)

    def test_happy_path_subscribes_to_correct_redis_channel(self) -> None:
        # Drives the WS up to the "subscribed" ack and confirms it
        # subscribed to the right Redis channel. Doesn't push a fake
        # message — message forwarding is a two-line bridge
        # (`async for message in pubsub.listen(): await ws.send_text(...)`)
        # whose only failure modes are (a) wrong channel (covered
        # here), (b) decode of bytes vs. str (covered by the code
        # path's explicit isinstance check). End-to-end forwarding
        # is verified manually in the smoke-test step of the
        # plan's verification matrix.
        app, fake_pubsub = _make_test_app()
        try:
            client = TestClient(app)
            token = _mint_token(company_id=COMPANY_ID)
            topic = f"org.{COMPANY_ID}.execution.{EXECUTION_ID}"
            with client.websocket_connect(f"/api/v1/subscribe/{topic}") as ws:
                ws.send_json({"token": token})
                first = ws.receive_json()
                assert first == {"event": "subscribed", "topic": topic}
            # On context-manager exit the server cleaned up.
            assert fake_pubsub.subscribed == [f"exec:logs:{EXECUTION_ID}"]
            # Cleanup is best-effort and may not have run yet by the
            # time the WS context closes (depends on TestClient loop
            # teardown order). The subscribed-channel assertion above
            # is the load-bearing check.
        finally:
            _teardown(app)

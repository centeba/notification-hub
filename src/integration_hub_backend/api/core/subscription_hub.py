"""Process-wide WebSocket fan-out over a SINGLE Redis pub/sub connection.

Previously every WebSocket subscriber (``subscription_bus.subscribe``) opened
its own ``redis.pubsub()``. Each pubsub holds one dedicated Redis connection,
so N live WS streams meant N connections against the 50-max pool
(``core/redis.py``): a few dozen concurrent streams exhausted the pool and
further connects — including ordinary request handlers — failed. That caps how
many replicas/clients a deployment can carry, which is exactly what the
single-AZ HA bar can't tolerate.

This hub holds ONE pubsub connection for the whole process and fans each Redis
message out to every local subscriber of that channel via in-memory queues, so
Redis connection use is O(1) in the number of WebSocket clients instead of
O(N). A single background reader owns all reads on the pubsub connection; an
``asyncio.Lock`` serializes it against dynamic ``subscribe``/``unsubscribe`` so
they never issue commands on the connection concurrently (redis-py's async
PubSub is not safe for concurrent command + read on one connection).

Resilience:
- **Backpressure:** each subscriber has a bounded queue; a slow WS client only
  loses its own oldest messages (drop-oldest), never stalls the hub or other
  clients.
- **Reconnect:** on a Redis read error the reader re-subscribes every live
  channel and retries — a Redis blip degrades to a brief gap, not a dead bus.
- **Drain:** :func:`close_subscription_hub` cancels the reader and closes the
  pubsub on shutdown (wired into the app's shutdown hook).
"""

import asyncio
import contextlib
import logging
from collections import defaultdict

import redis.asyncio as aioredis

logger = logging.getLogger(__name__)

# Per-subscriber buffer. Execution-log bursts are small JSON frames; 1000 gives
# a slow browser plenty of slack before we start dropping its oldest frames.
_QUEUE_MAXSIZE = 1000
# How long the reader waits for a message before looping (bounds how long the
# lock is held away from subscribe/unsubscribe when idle). A message that
# arrives sooner returns immediately, so this is not added latency.
_IDLE_POLL_TIMEOUT = 0.2
# When no channels are subscribed the reader parks on this event; the wake-up
# timeout is just a safety re-check.
_IDLE_PARK_TIMEOUT = 5.0


class Subscriber:
    """One WebSocket's view onto a channel: a bounded in-memory queue."""

    __slots__ = ("channel", "queue", "dropped")

    def __init__(self, channel: str) -> None:
        self.channel = channel
        self.queue: asyncio.Queue[str] = asyncio.Queue(maxsize=_QUEUE_MAXSIZE)
        self.dropped = 0


class SubscriptionHub:
    """Fan-out from one shared pubsub connection to many local subscribers."""

    def __init__(self, redis: aioredis.Redis) -> None:
        self._redis = redis
        self._pubsub = redis.pubsub()
        self._subs: dict[str, set[Subscriber]] = defaultdict(set)
        self._lock = asyncio.Lock()
        self._wake = asyncio.Event()
        self._reader: asyncio.Task[None] | None = None
        self._closed = False

    async def subscribe(self, channel: str) -> Subscriber:
        """Register a subscriber for ``channel``; SUBSCRIBE on Redis if first."""
        sub = Subscriber(channel)
        async with self._lock:
            first = not self._subs[channel]
            self._subs[channel].add(sub)
            if first:
                await self._pubsub.subscribe(channel)
            if self._reader is None or self._reader.done():
                self._reader = asyncio.create_task(self._run())
        self._wake.set()
        return sub

    async def unsubscribe(self, sub: Subscriber) -> None:
        """Deregister a subscriber; UNSUBSCRIBE on Redis if it was the last."""
        async with self._lock:
            subs = self._subs.get(sub.channel)
            if not subs:
                return
            subs.discard(sub)
            if not subs:
                self._subs.pop(sub.channel, None)
                with contextlib.suppress(Exception):
                    await self._pubsub.unsubscribe(sub.channel)

    def _dispatch(self, channel: str, data: str) -> None:
        # Runs synchronously (no await) so the subscriber set can't mutate
        # mid-iteration; snapshot anyway for defensiveness.
        for sub in tuple(self._subs.get(channel, ())):
            try:
                sub.queue.put_nowait(data)
            except asyncio.QueueFull:
                # Slow consumer: drop its oldest frame to keep the stream fresh.
                # Only this subscriber is affected.
                with contextlib.suppress(Exception):
                    sub.queue.get_nowait()
                    sub.queue.put_nowait(data)
                    sub.dropped += 1

    async def _run(self) -> None:
        while not self._closed:
            if not self._subs:
                self._wake.clear()
                with contextlib.suppress(asyncio.TimeoutError):
                    await asyncio.wait_for(self._wake.wait(), timeout=_IDLE_PARK_TIMEOUT)
                continue
            try:
                async with self._lock:
                    if not self._subs:
                        continue
                    msg = await self._pubsub.get_message(
                        ignore_subscribe_messages=True,
                        timeout=_IDLE_POLL_TIMEOUT,
                    )
                if msg is None or msg.get("type") != "message":
                    continue
                channel = msg["channel"]
                if isinstance(channel, bytes):
                    channel = channel.decode("utf-8", "replace")
                data = msg["data"]
                if isinstance(data, bytes):
                    data = data.decode("utf-8", "replace")
                self._dispatch(channel, data)
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001 — a Redis blip must not kill the bus
                logger.warning(
                    "subscription_hub reader error; re-subscribing live channels",
                    exc_info=True,
                )
                await self._resubscribe_all()
                await asyncio.sleep(0.5)

    async def _resubscribe_all(self) -> None:
        async with self._lock:
            channels = list(self._subs.keys())
        if not channels:
            return
        with contextlib.suppress(Exception):
            await self._pubsub.subscribe(*channels)

    async def aclose(self) -> None:
        """Stop the reader and close the shared pubsub connection."""
        self._closed = True
        self._wake.set()
        if self._reader is not None:
            self._reader.cancel()
            # Awaiting a cancelled task re-raises CancelledError, which is a
            # BaseException (not Exception) — suppress it explicitly.
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await self._reader
            self._reader = None
        with contextlib.suppress(Exception):
            # redis-py's PubSub.aclose() ships without a return annotation
            # (inline types), so strict mypy sees an untyped call here.
            await self._pubsub.aclose()  # type: ignore[no-untyped-call]


# ── Process singleton ────────────────────────────────────────────────────────
_hub: SubscriptionHub | None = None


def get_subscription_hub() -> SubscriptionHub:
    """Lazily build the process-wide hub bound to the shared Redis pool."""
    global _hub
    if _hub is None:
        from integration_hub_backend.api.core.redis import get_redis_pool

        _hub = SubscriptionHub(get_redis_pool())
    return _hub


async def close_subscription_hub() -> None:
    """Shutdown hook: drain the hub (idempotent)."""
    global _hub
    if _hub is not None:
        await _hub.aclose()
        _hub = None

"""Shared per-IP rate-limit middleware (HARDENING-PLAN A4).

One Redis-backed limiter every service can mount, instead of each rolling its
own SlowAPI/in-memory limiter that silently *fails open* when Redis is down.

Configurable failure policy for when the Redis backend is unreachable — the A4
requirement is to never *silently* allow unlimited traffic:

  * ``"closed"`` — deny (503) on the limited endpoints. Use for the abuse-prone
    public/M2M surface where "no rate limiter" is unacceptable.
  * ``"degrade"`` (default) — fall back to an in-process counter (still limits,
    but per-replica, not cluster-wide) and log a throttled WARNING.
  * ``"open"`` — allow through, but log a throttled WARNING so the gap is visible.

Rules are ``(path_prefix, max_requests, window_seconds)``, first match wins.
Only matched paths are limited; everything else passes straight through. A
hardened edge (nginx ``limit_req``) remains the recommended front line at scale.
"""

import logging
import time
from collections import defaultdict, deque
from typing import Literal

from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

logger = logging.getLogger("integration_hub_backend.rate_limit")

FailPolicy = Literal["closed", "degrade", "open"]

# Atomic fixed-window counter: INCR then set TTL on the first hit, so the window
# lives server-side and every replica shares one counter.
_INCR_EXPIRE_LUA = (
    "local c = redis.call('INCR', KEYS[1]) "
    "if c == 1 then redis.call('EXPIRE', KEYS[1], ARGV[1]) end "
    "return c"
)

Rule = tuple[str, int, float]


class RateLimitMiddleware:
    """Pure-ASGI per-client-IP limiter keyed by endpoint bucket.

    Args:
        app: the ASGI app to wrap.
        rules: ``(path_prefix, max_requests, window_seconds)`` tuples; first
            prefix match wins. Unmatched paths are never limited.
        redis: an async Redis client (``.eval`` coroutine). None → in-process only.
        fail_policy: behavior when Redis is unreachable (see module docstring).
        key_prefix: Redis key namespace.
    """

    def __init__(
        self,
        app: ASGIApp,
        *,
        rules: list[Rule],
        redis: object | None = None,
        fail_policy: FailPolicy = "degrade",
        key_prefix: str = "rl",
        exclude_prefixes: tuple[str, ...] = (),
    ) -> None:
        self.app = app
        self._rules = rules
        self._redis = redis
        self._fail_policy: FailPolicy = fail_policy
        self._key_prefix = key_prefix
        # Paths that bypass limiting entirely — liveness/readiness/metrics, which
        # the platform polls frequently and must never be throttled (a blanket
        # ``("/", …)`` rule would otherwise match them).
        self._exclude_prefixes = exclude_prefixes
        self._hits: dict[tuple[str, str], deque[float]] = defaultdict(deque)
        self._last_warn = 0.0

    def _bucket(self, path: str) -> Rule | None:
        if any(path.startswith(p) for p in self._exclude_prefixes):
            return None
        for prefix, limit, window in self._rules:
            if path.startswith(prefix):
                return prefix, limit, window
        return None

    @staticmethod
    def _client_ip(scope: Scope) -> str:
        for name, value in scope.get("headers", []):
            if name == b"x-forwarded-for":
                forwarded: str = value.decode("latin-1").split(",")[0].strip()
                return forwarded
        client = scope.get("client")
        if client:
            host: str = client[0]
            return host
        return "unknown"

    def _warn(self, exc: Exception) -> None:
        now = time.monotonic()
        if now - self._last_warn > 30.0:
            self._last_warn = now
            logger.warning(
                "rate-limit Redis backend unavailable (%s) — fail_policy=%s",
                exc,
                self._fail_policy,
            )

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        rule = self._bucket(scope.get("path", ""))
        if rule is None:
            await self.app(scope, receive, send)
            return

        bucket_key, limit, window = rule
        ip = self._client_ip(scope)
        decision = await self._decide(ip, bucket_key, limit, window)
        if decision == "deny":
            await JSONResponse(
                {"detail": "Too many requests"},
                status_code=429,
                headers={"Retry-After": str(int(window))},
            )(scope, receive, send)
            return
        if decision == "unavailable":
            await JSONResponse(
                {"detail": "Rate limiter unavailable"},
                status_code=503,
                headers={"Retry-After": str(int(window))},
            )(scope, receive, send)
            return
        await self.app(scope, receive, send)

    async def _decide(
        self, ip: str, bucket_key: str, limit: int, window: float
    ) -> Literal["allow", "deny", "unavailable"]:
        if self._redis is not None:
            try:
                window_idx = int(time.time() // window)
                key = f"{self._key_prefix}:{bucket_key}:{ip}:{window_idx}"
                count = await self._redis.eval(  # type: ignore[attr-defined]
                    _INCR_EXPIRE_LUA, 1, key, str(int(window) + 1)
                )
                return "deny" if int(count) > limit else "allow"
            except Exception as exc:  # noqa: BLE001 — Redis backend down
                self._warn(exc)
                if self._fail_policy == "closed":
                    return "unavailable"
                if self._fail_policy == "open":
                    return "allow"
                # "degrade" → fall through to the in-process backstop below.
        elif self._fail_policy == "closed":
            # Configured fail-closed but no Redis wired at all: deny rather than
            # pretend to enforce a cluster-wide limit we can't.
            return "unavailable"
        return "deny" if self._over_limit_memory(ip, bucket_key, limit, window) else "allow"

    def _over_limit_memory(self, ip: str, bucket_key: str, limit: int, window: float) -> bool:
        now = time.monotonic()
        if len(self._hits) > 50_000:  # memory backstop
            self._hits.clear()
        dq = self._hits[(ip, bucket_key)]
        cutoff = now - window
        while dq and dq[0] <= cutoff:
            dq.popleft()
        if len(dq) >= limit:
            return True
        dq.append(now)
        return False


# Default platform-wide blanket cap: a generous per-IP ceiling on *every* path
# so a single client can't flood any service, without interfering with normal
# tenant traffic or the fine-grained per-endpoint limits some services already
# run (login/2FA/public-submit). Health & metrics are always exempt.
_DEFAULT_RULES: list[Rule] = [("/", 600, 60.0)]
_DEFAULT_EXCLUDE: tuple[str, ...] = ("/health", "/healthz", "/metrics")
_RATE_LIMIT_REDIS_ENV = "RATE_LIMIT_REDIS_URL"

_installed_clients: dict[str, object] = {}


def install_rate_limit(
    app: ASGIApp,
    *,
    service_name: str = "",
    redis: object | None = None,
    rules: list[Rule] | None = None,
    fail_policy: FailPolicy = "degrade",
    exclude_prefixes: tuple[str, ...] = _DEFAULT_EXCLUDE,
    env_var: str = _RATE_LIMIT_REDIS_ENV,
) -> bool:
    """Mount the shared per-IP :class:`RateLimitMiddleware` on ``app``.

    Platform-wide convention alongside ``install_observability`` /
    ``add_readiness_route``: every API service calls this once. It is a **no-op
    unless a Redis URL is available** — passed as ``redis`` (an async client) or,
    more usually, discovered from ``env_var`` (``RATE_LIMIT_REDIS_URL``) — so
    wiring it into every service can't change behavior before an operator opts in
    by setting that env var. Returns ``True`` when the middleware was mounted.

    Defaults to a generous blanket cap (600 req / 60 s per IP on every path bar
    health/metrics) with ``fail_policy="degrade"`` (falls back to a per-replica
    in-process counter if Redis blips — never a hard outage). Services with
    abuse-prone endpoints can pass tighter ``rules``.
    """
    client = redis
    if client is None:
        import os

        url = os.environ.get(env_var)
        if not url:
            logger.debug(
                "rate limit not mounted for %s — %s unset (opt-in)",
                service_name or "service",
                env_var,
            )
            return False
        if url not in _installed_clients:
            try:
                from redis.asyncio import from_url

                _installed_clients[url] = from_url(url, decode_responses=True)
            except Exception:  # noqa: BLE001 — never let wiring break startup
                logger.warning("rate_limit_redis_init_failed", exc_info=True)
                _installed_clients[url] = None
        client = _installed_clients[url]
        if client is None:
            return False

    app.add_middleware(  # type: ignore[attr-defined]
        RateLimitMiddleware,
        rules=rules if rules is not None else _DEFAULT_RULES,
        redis=client,
        fail_policy=fail_policy,
        key_prefix=f"rl:{service_name}" if service_name else "rl",
        exclude_prefixes=exclude_prefixes,
    )
    logger.info("rate_limit_installed service=%s policy=%s", service_name, fail_policy)
    return True


def _reset_rate_limit_clients_for_tests() -> None:
    _installed_clients.clear()

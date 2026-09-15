"""HMAC signing and verification for inter-service webhooks.

Header conventions:
- X-Sentinel-Signature: sha256=<hex>
- X-Sentinel-Timestamp: <unix-epoch-seconds>

Signature is HMAC-SHA256 over `f"{timestamp}.{body}"` with the shared webhook secret.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import time
from typing import Any

from integration_hub_backend._platform.errors import WebhookVerificationError

logger = logging.getLogger(__name__)

WEBHOOK_SIGNATURE_HEADER = "X-Sentinel-Signature"
WEBHOOK_TIMESTAMP_HEADER = "X-Sentinel-Timestamp"
_DEFAULT_MAX_AGE_SECONDS = 300
_REPLAY_PREFIX = "sb:webhook:seen:"


def _compute_signature(secret: str, timestamp: str, body: bytes) -> str:
    payload = f"{timestamp}.".encode() + body
    digest = hmac.new(secret.encode("utf-8"), payload, hashlib.sha256).hexdigest()
    return f"sha256={digest}"


def sign_webhook(body: bytes, secret: str, *, timestamp: int | None = None) -> dict[str, str]:
    """Produce the headers needed to send a signed webhook.

    Example::

        headers = sign_webhook(body=json.dumps(payload).encode(), secret=settings.webhook_secret)
        await httpx.post(url, content=body, headers=headers)
    """
    if not secret:
        raise WebhookVerificationError("Webhook secret is empty — refusing to sign")
    ts = str(timestamp if timestamp is not None else int(time.time()))
    return {
        WEBHOOK_TIMESTAMP_HEADER: ts,
        WEBHOOK_SIGNATURE_HEADER: _compute_signature(secret, ts, body),
    }


def verify_webhook(
    body: bytes,
    *,
    signature_header: str | None,
    timestamp_header: str | None,
    secret: str,
    max_age_seconds: int = _DEFAULT_MAX_AGE_SECONDS,
) -> None:
    """Raise WebhookVerificationError if the signature is missing, malformed, stale, or wrong."""
    if not signature_header or not timestamp_header:
        raise WebhookVerificationError("Missing signature or timestamp header")
    if not secret:
        raise WebhookVerificationError("Webhook secret is empty — cannot verify")

    try:
        ts = int(timestamp_header)
    except ValueError as exc:
        raise WebhookVerificationError(f"Invalid timestamp: {timestamp_header!r}") from exc

    age = abs(int(time.time()) - ts)
    if age > max_age_seconds:
        raise WebhookVerificationError(
            f"Webhook timestamp too old or skewed: age={age}s, max={max_age_seconds}s"
        )

    expected = _compute_signature(secret, str(ts), body)
    if not hmac.compare_digest(expected, signature_header):
        raise WebhookVerificationError("Signature mismatch")


# ── Replay protection (Gate 7) ────────────────────────────────────────────────
# Signature + timestamp alone leave a replay window: within ``max_age_seconds`` a
# captured request re-verifies. The signature is a deterministic nonce over
# (secret, timestamp, body), so recording it once (SET NX EX) makes it single-
# use for the window. Requires a shared Redis so all receiver replicas see the
# same record.
_replay_clients: dict[str, Any] = {}


def _replay_redis(url: str) -> Any:
    if not url:
        return None
    if url not in _replay_clients:
        try:
            from redis.asyncio import from_url

            _replay_clients[url] = from_url(url, decode_responses=True)
        except Exception:  # noqa: BLE001 — never let wiring break verification
            logger.warning("webhook_replay_redis_init_failed", exc_info=True)
            _replay_clients[url] = None
    return _replay_clients[url]


async def is_webhook_replay(
    signature_header: str,
    *,
    redis_url: str,
    ttl_seconds: int = _DEFAULT_MAX_AGE_SECONDS,
) -> bool:
    """Record a verified webhook's signature and return True if it was ALREADY
    seen within ``ttl_seconds`` (a replay). No-op (returns False) when
    ``redis_url`` is empty or Redis errors — fail-open, since the timestamp
    window is the backstop. Call only AFTER :func:`verify_webhook` succeeds."""
    r = _replay_redis(redis_url)
    if r is None or not signature_header:
        return False
    key = _REPLAY_PREFIX + hashlib.sha256(signature_header.encode("utf-8")).hexdigest()
    try:
        # SET key NX EX ttl → truthy on first set, None if it already existed.
        first_seen = await r.set(key, "1", nx=True, ex=max(1, ttl_seconds))
    except Exception:  # noqa: BLE001 — replay store is best-effort
        logger.warning("webhook_replay_check_failed", exc_info=True)
        return False
    return not first_seen


def _reset_replay_clients_for_tests() -> None:
    _replay_clients.clear()

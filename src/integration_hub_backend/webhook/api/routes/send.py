"""Webhook outbound call endpoint with SSRF protection and HMAC signing."""

from __future__ import annotations

import hashlib
import hmac
import json
import os
from typing import Any

import httpx
import structlog
from fastapi import APIRouter, Depends, HTTPException, Security, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel

from integration_hub_backend._platform.ssrf import SsrfError, guarded_send

log = structlog.get_logger(__name__)
router = APIRouter()
bearer = HTTPBearer()

# SSRF protection is delegated to the shared canonical guard
# (sentinelbuild_sdk.ssrf), which additionally pins the validated IP at connect
# time to close the DNS-rebind window and re-validates every redirect hop.


# ── HMAC Signing ─────────────────────────────────────────────────────────────


def _sign_payload(payload_bytes: bytes, secret: str) -> str:
    sig = hmac.new(secret.encode(), payload_bytes, hashlib.sha256).hexdigest()
    return f"sha256={sig}"


# ── Auth ──────────────────────────────────────────────────────────────────────


def _get_internal_secret() -> str:
    secret = os.environ.get("INTERNAL_SERVICE_SECRET", "")
    if not secret:
        raise RuntimeError(
            "INTERNAL_SERVICE_SECRET environment variable must be set; "
            "service-to-service calls will be rejected until it is configured."
        )
    return secret


def verify_internal_token(
    credentials: HTTPAuthorizationCredentials = Security(bearer),
) -> None:
    secret = _get_internal_secret()
    if not hmac.compare_digest(credentials.credentials, secret):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid service token"
        )


# ── Request/Response ──────────────────────────────────────────────────────────


class SendWebhookRequest(BaseModel):
    url: str
    method: str = "POST"
    payload: dict[str, Any] = {}
    auth_type: str = "none"  # none | bearer | basic | hmac
    auth_config: dict[str, Any] = {}
    timeout_seconds: int = 30
    signing_secret: str | None = None  # for HMAC signature header


class SendWebhookResponse(BaseModel):
    status_code: int
    status: str


@router.post("/send", response_model=SendWebhookResponse)
async def send_webhook(
    body: SendWebhookRequest,
    _: None = Depends(verify_internal_token),
) -> SendWebhookResponse:
    payload_bytes = json.dumps(body.payload, default=str).encode()

    headers: dict[str, str] = {
        "Content-Type": "application/json",
        "User-Agent": "NotificationHub/1.0",
    }

    # Auth header
    if body.auth_type == "bearer":
        token = body.auth_config.get("token", "")
        headers["Authorization"] = f"Bearer {token}"
    elif body.auth_type == "basic":
        import base64

        creds = f"{body.auth_config.get('username', '')}:{body.auth_config.get('password', '')}"
        encoded = base64.b64encode(creds.encode()).decode()
        headers["Authorization"] = f"Basic {encoded}"

    # HMAC signature
    _hmac_secret = ""
    if body.signing_secret:
        headers["X-Hub-Signature-256"] = _sign_payload(payload_bytes, body.signing_secret)
        _hmac_secret = body.signing_secret
    elif body.auth_type == "hmac":
        secret = body.auth_config.get("secret", "")
        if secret:
            headers["X-Hub-Signature-256"] = _sign_payload(payload_bytes, secret)
            _hmac_secret = secret
    # M1 — also emit the SDK's timestamped signature (HMAC over "{ts}.{body}")
    # so receivers can verify with replay protection (a stale/replayed delivery
    # is rejected by the freshness window). The body-only X-Hub-Signature-256
    # above stays for backward compatibility with existing subscribers.
    if _hmac_secret:
        try:
            from integration_hub_backend._platform.webhooks import sign_webhook

            headers.update(sign_webhook(payload_bytes, _hmac_secret))
        except Exception:  # noqa: BLE001 — never block a send on the extra header
            pass

    try:
        # follow_redirects=False so the shared guard walks + re-pins each hop.
        async with httpx.AsyncClient(
            timeout=body.timeout_seconds, follow_redirects=False
        ) as client:
            response = await guarded_send(
                client,
                body.method,
                body.url,
                headers=headers,
                content=payload_bytes,
            )
            log.info("webhook_sent", url=body.url, status_code=response.status_code)
            return SendWebhookResponse(status_code=response.status_code, status="sent")
    except SsrfError as exc:
        # Blocked target (or redirect target) — a 400 client error, not a 502.
        log.warning("webhook_ssrf_blocked", url=body.url, error=str(exc))
        raise HTTPException(status_code=400, detail=f"Webhook URL blocked: {exc}")
    except httpx.TimeoutException:
        log.error("webhook_timeout", url=body.url)
        raise HTTPException(status_code=504, detail="Webhook request timed out")
    except Exception as e:
        log.error("webhook_send_failed", url=body.url, error=str(e))
        raise HTTPException(status_code=502, detail=f"Webhook delivery failed: {e}")

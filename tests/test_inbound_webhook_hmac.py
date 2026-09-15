"""Inbound-webhook HMAC gate on /events/ingest (HARDENING-PLAN C1).

The SDK's constant-time HMAC verifier was shipped but dormant. `optional_
webhook_signature` mounts it as a config-gated second factor: a no-op when
`WEBHOOK_SECRET` is unset (API-key auth only, unchanged), and a hard 401 on
missing/invalid signatures when the secret is set.
"""

from __future__ import annotations

import pytest
from fastapi import HTTPException

from integration_hub_backend.api.api.deps import (
    WEBHOOK_SIGNATURE_HEADER,
    optional_webhook_signature,
)
from integration_hub_backend.api.core.config import settings
from integration_hub_backend.api.core.security import sign_webhook_payload

_BODY = b'{"event_type":"demo","payload":{}}'


class _Req:
    def __init__(self, headers: dict[str, str], body: bytes = _BODY) -> None:
        self.headers = headers
        self._body = body

    async def body(self) -> bytes:
        return self._body


async def test_noop_when_secret_unset(monkeypatch):
    monkeypatch.setattr(settings, "WEBHOOK_SECRET", "")
    # No signature at all, yet the gate passes (API-key auth still applies).
    assert await optional_webhook_signature(_Req({})) is None


async def test_missing_signature_rejected_when_secret_set(monkeypatch):
    monkeypatch.setattr(settings, "WEBHOOK_SECRET", "s3cr3t-value")
    with pytest.raises(HTTPException) as ei:
        await optional_webhook_signature(_Req({}))
    assert ei.value.status_code == 401


async def test_invalid_signature_rejected(monkeypatch):
    monkeypatch.setattr(settings, "WEBHOOK_SECRET", "s3cr3t-value")
    req = _Req({WEBHOOK_SIGNATURE_HEADER: "sha256=deadbeef"})
    with pytest.raises(HTTPException) as ei:
        await optional_webhook_signature(req)
    assert ei.value.status_code == 401


async def test_valid_signature_passes(monkeypatch):
    secret = "s3cr3t-value"
    monkeypatch.setattr(settings, "WEBHOOK_SECRET", secret)
    good = sign_webhook_payload(_BODY, secret)  # "sha256=<hex>"
    req = _Req({WEBHOOK_SIGNATURE_HEADER: good})
    assert await optional_webhook_signature(req) is None


async def test_signature_over_different_body_rejected(monkeypatch):
    secret = "s3cr3t-value"
    monkeypatch.setattr(settings, "WEBHOOK_SECRET", secret)
    # Signature computed over a DIFFERENT body → tampered payload → 401.
    good_for_other = sign_webhook_payload(b"other-body", secret)
    req = _Req({WEBHOOK_SIGNATURE_HEADER: good_for_other}, body=_BODY)
    with pytest.raises(HTTPException) as ei:
        await optional_webhook_signature(req)
    assert ei.value.status_code == 401

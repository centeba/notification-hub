"""Webhook HMAC sign/verify tests.

Ported from the retired standalone ``notification-api`` service. (Field
encryption is already covered by ``test_security.py``; this fills the one gap —
the outbound-webhook signature primitives.)
"""

from __future__ import annotations

from integration_hub_backend.api.core.security import (
    sign_webhook_payload,
    verify_webhook_signature,
)


def test_webhook_hmac_sign_and_verify():
    payload = b'{"order_id": "123"}'
    secret = "super-secret-webhook-key"
    signature = sign_webhook_payload(payload, secret)
    assert signature.startswith("sha256=")
    assert verify_webhook_signature(payload, secret, signature) is True


def test_webhook_hmac_tampered_payload():
    payload = b'{"order_id": "123"}'
    secret = "super-secret-webhook-key"
    signature = sign_webhook_payload(payload, secret)
    tampered = b'{"order_id": "456"}'
    assert verify_webhook_signature(tampered, secret, signature) is False


def test_webhook_hmac_wrong_secret():
    payload = b'{"data": "test"}'
    signature = sign_webhook_payload(payload, "secret1")
    assert verify_webhook_signature(payload, "secret2", signature) is False

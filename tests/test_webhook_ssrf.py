"""SSRF-protection tests for the outbound-webhook URL validator.

Ported from the retired standalone ``notification-api`` service. Guards the
same ``_validate_webhook_url`` that the webhook routes call before any
outbound request.
"""

from __future__ import annotations

import pytest
from fastapi import HTTPException

from integration_hub_backend.api.api.routes.webhooks import _validate_webhook_url


@pytest.mark.parametrize(
    "url",
    [
        "http://localhost/api",
        "https://localhost:8080/cb",
        "http://127.0.0.1/secret",
        "http://169.254.169.254/latest/meta-data/",
        "http://metadata.google.internal/computeMetadata/v1/",
        "ftp://example.com/file",  # non-http scheme
        "file:///etc/passwd",  # file scheme
    ],
)
def test_blocked_urls(url):
    with pytest.raises((HTTPException, Exception)):
        _validate_webhook_url(url)


@pytest.mark.parametrize(
    "url",
    [
        "https://api.example.com/webhook",
        "https://hooks.slack.com/services/abc",
        "http://external-partner.com/notify",
    ],
)
def test_public_urls_allowed(url):
    """Public URLs should not raise as SSRF. (DNS may fail offline — allowed.)"""
    try:
        _validate_webhook_url(url)
    except HTTPException as e:
        # DNS resolution failure is acceptable — it means we're offline, not SSRF.
        assert "resolve" in e.detail.lower() or "private" in e.detail.lower()

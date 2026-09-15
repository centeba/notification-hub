"""Minimal error types used by the vendored platform helpers."""


class WebhookVerificationError(Exception):
    """HMAC signature missing, malformed, or doesn't match the body."""

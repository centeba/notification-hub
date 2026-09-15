"""SMS provider factory."""

from __future__ import annotations

from typing import Any

from integration_hub_backend.sms.providers.aws_sns_provider import AWSSNSProvider
from integration_hub_backend.sms.providers.base import SMSProvider
from integration_hub_backend.sms.providers.twilio_provider import TwilioProvider


def get_provider(provider_name: str, config: dict[str, Any]) -> SMSProvider:
    """Factory function — returns the appropriate SMS provider."""
    if provider_name == "twilio":
        return TwilioProvider(
            account_sid=config.get("account_sid", ""),
            auth_token=config.get("auth_token", ""),
            from_number=config.get("from_number", ""),
        )
    elif provider_name == "aws_sns":
        return AWSSNSProvider(
            access_key_id=config.get("access_key_id", ""),
            secret_access_key=config.get("secret_access_key", ""),
            region=config.get("region", "us-east-1"),
            sender_id=config.get("sender_id", "NotifHub"),
        )
    raise ValueError(f"Unknown SMS provider: {provider_name}")

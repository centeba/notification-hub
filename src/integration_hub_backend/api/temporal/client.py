"""Temporal client singleton."""

from __future__ import annotations

from temporalio.client import Client

from integration_hub_backend.api.core.config import settings

_temporal_client: Client | None = None


async def get_temporal_client() -> Client:
    global _temporal_client
    if _temporal_client is None:
        # TEMPORAL_API_KEY is unset by default (self-hosted Temporal, no
        # auth — matches today's behavior exactly). Setting it points this
        # at Temporal Cloud instead: API-key auth requires TLS, so
        # `tls=True` is implied whenever a key is present.
        api_key = getattr(settings, "TEMPORAL_API_KEY", "") or None
        _temporal_client = await Client.connect(
            settings.TEMPORAL_ADDRESS,
            namespace=settings.TEMPORAL_NAMESPACE,
            api_key=api_key,
            tls=bool(api_key),
        )
    return _temporal_client


async def close_temporal_client() -> None:
    global _temporal_client
    _temporal_client = None

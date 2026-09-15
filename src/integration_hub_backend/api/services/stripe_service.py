"""Service for interacting with Stripe (Global)."""

from types import ModuleType
from typing import Any

import stripe

from integration_hub_backend.api.services.observability_service import ObservabilityService


class StripeService:
    def __init__(self, observability_service: ObservabilityService):
        self.obs = observability_service

    async def _get_client(self) -> ModuleType:
        """Prepare the Stripe client with global credentials."""
        config = await self.obs.get_decrypted_config("stripe")
        api_key = config.get("api_key")
        if not api_key:
            raise ValueError("Stripe API key is not configured globally.")
        stripe.api_key = api_key
        return stripe

    async def get_customer(self, customer_id: str) -> dict[str, Any]:
        """Fetch a Stripe customer."""
        client = await self._get_client()
        result: dict[str, Any] = client.Customer.retrieve(customer_id).to_dict()
        return result

    async def create_payment_intent(
        self, amount: int, currency: str = "usd", **kwargs: Any
    ) -> dict[str, Any]:
        """Create a Stripe payment intent."""
        client = await self._get_client()
        result: dict[str, Any] = client.PaymentIntent.create(
            amount=amount, currency=currency, **kwargs
        ).to_dict()
        return result

    async def list_invoices(self, limit: int = 10) -> list[dict[str, Any]]:
        """List recent Stripe invoices."""
        client = await self._get_client()
        invoices = client.Invoice.list(limit=limit)
        return [inv.to_dict() for inv in invoices.data]

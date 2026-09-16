"""Service for interacting with Stripe.

Credentials are resolved per-tenant (Connect-UI credential) with a global
``SystemIntegration`` fallback — see ``resolve_integration_secrets``.
"""

import uuid
from types import ModuleType
from typing import Any

import stripe

from integration_hub_backend.api.services.integration_secrets import resolve_integration_secrets
from integration_hub_backend.api.services.observability_service import ObservabilityService


class StripeService:
    def __init__(
        self,
        observability_service: ObservabilityService,
        company_id: uuid.UUID | None = None,
    ):
        self.obs = observability_service
        self.company_id = company_id

    async def _get_client(self) -> ModuleType:
        """Prepare the Stripe client from the tenant's credential."""
        config = await resolve_integration_secrets(self.obs.db, "stripe", self.company_id)
        api_key = config.get("api_key")
        if not api_key:
            raise ValueError(
                "Stripe is not connected. Connect it on the Integrations page (api_key)."
            )
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

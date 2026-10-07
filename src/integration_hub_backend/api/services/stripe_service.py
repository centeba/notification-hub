"""Service for interacting with Stripe.

Credentials are resolved per-tenant (Connect-UI credential) with a global
``SystemIntegration`` fallback — see ``resolve_integration_secrets``.

Every call builds its own ``StripeClient`` from the tenant's key. The legacy
module-level ``stripe.api_key`` is deliberately never written: it is
process-global, so assigning it per request would let concurrent tenants' calls
run with each other's keys. The ``*_async`` client methods are used so the
event loop isn't blocked.
"""

import uuid
from typing import Any, cast

from stripe import StripeClient

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

    async def _get_client(self) -> StripeClient:
        """Build a per-call Stripe client from the tenant's credential."""
        config = await resolve_integration_secrets(self.obs.db, "stripe", self.company_id)
        api_key = config.get("api_key")
        if not api_key:
            raise ValueError(
                "Stripe is not connected. Connect it on the Integrations page (api_key)."
            )
        return StripeClient(api_key)

    async def get_customer(self, customer_id: str) -> dict[str, Any]:
        """Fetch a Stripe customer."""
        client = await self._get_client()
        customer = await client.v1.customers.retrieve_async(customer_id)
        return customer.to_dict()

    async def create_payment_intent(
        self,
        amount: int,
        currency: str = "usd",
        description: str | None = None,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        """Create a Stripe payment intent.

        ``idempotency_key`` is forwarded to Stripe so a client retry of the same
        request can't create a second intent; it must be supplied (and reused)
        by the caller, which is the only party that knows a retry is a retry.
        """
        client = await self._get_client()
        params: dict[str, Any] = {"amount": amount, "currency": currency}
        if description is not None:
            params["description"] = description
        # The SDK types params/options as TypedDicts; the dicts above are built
        # from validated request fields, so cast rather than re-declare them.
        options = cast(Any, {"idempotency_key": idempotency_key}) if idempotency_key else None
        intent = await client.v1.payment_intents.create_async(cast(Any, params), options=options)
        return intent.to_dict()

    async def list_invoices(self, limit: int = 10) -> list[dict[str, Any]]:
        """List recent Stripe invoices."""
        client = await self._get_client()
        invoices = await client.v1.invoices.list_async(cast(Any, {"limit": limit}))
        return [inv.to_dict() for inv in invoices.data]

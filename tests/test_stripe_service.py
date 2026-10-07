"""Regression tests for StripeService's per-tenant, per-call client.

The service used to assign the tenant's key to the process-global
``stripe.api_key`` on every call. Under per-tenant credentials that is a
cross-tenant race: two concurrent requests would run with each other's keys.
These tests pin that the global is never written and that each call gets a
client built from its own tenant's key.
"""

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import stripe

from integration_hub_backend.api.services.stripe_service import StripeService

MOD = "integration_hub_backend.api.services.stripe_service"


def _client_factory(built_with: list[str], clients: list[MagicMock]) -> MagicMock:
    """A ``StripeClient`` stand-in recording the key and instance of every build."""

    def factory(api_key: str) -> MagicMock:
        built_with.append(api_key)
        client = MagicMock()
        customer = MagicMock()
        customer.to_dict.return_value = {"id": "cus_1", "built_with": api_key}
        client.v1.customers.retrieve_async = AsyncMock(return_value=customer)
        intent = MagicMock()
        intent.to_dict.return_value = {"id": "pi_1"}
        client.v1.payment_intents.create_async = AsyncMock(return_value=intent)
        invoice = MagicMock()
        invoice.to_dict.return_value = {"id": "in_1"}
        listing = MagicMock()
        listing.data = [invoice]
        client.v1.invoices.list_async = AsyncMock(return_value=listing)
        clients.append(client)
        return client

    return MagicMock(side_effect=factory)


def _service(company_id: uuid.UUID | None = None) -> StripeService:
    return StripeService(MagicMock(), company_id)


@pytest.mark.asyncio
async def test_builds_client_from_tenant_key_and_never_sets_global_api_key() -> None:
    assert stripe.api_key is None  # sanity: nothing has touched the global
    built_with: list[str] = []
    clients: list[MagicMock] = []
    with (
        patch(f"{MOD}.resolve_integration_secrets", new_callable=AsyncMock) as resolver,
        patch(f"{MOD}.StripeClient", _client_factory(built_with, clients)),
    ):
        resolver.return_value = {"api_key": "sk_tenant_a"}
        result = await _service().get_customer("cus_1")

    assert built_with == ["sk_tenant_a"]
    assert result["built_with"] == "sk_tenant_a"
    assert stripe.api_key is None  # the process-global was never written


@pytest.mark.asyncio
async def test_two_tenants_each_get_their_own_client() -> None:
    tenant_a, tenant_b = uuid.uuid4(), uuid.uuid4()
    keys = {tenant_a: "sk_tenant_a", tenant_b: "sk_tenant_b"}

    async def resolve(_db: object, _kind: str, company_id: uuid.UUID) -> dict[str, str]:
        return {"api_key": keys[company_id]}

    built_with: list[str] = []
    clients: list[MagicMock] = []
    with (
        patch(f"{MOD}.resolve_integration_secrets", side_effect=resolve),
        patch(f"{MOD}.StripeClient", _client_factory(built_with, clients)),
    ):
        a = await _service(tenant_a).get_customer("cus_a")
        b = await _service(tenant_b).get_customer("cus_b")
        a_again = await _service(tenant_a).list_invoices()

    assert a["built_with"] == "sk_tenant_a"
    assert b["built_with"] == "sk_tenant_b"
    assert a_again == [{"id": "in_1"}]
    # Interleaved calls never bleed one tenant's key into another's client.
    assert built_with == ["sk_tenant_a", "sk_tenant_b", "sk_tenant_a"]
    assert stripe.api_key is None


@pytest.mark.asyncio
async def test_payment_intent_forwards_idempotency_key_and_optional_description() -> None:
    built_with: list[str] = []
    clients: list[MagicMock] = []
    with (
        patch(f"{MOD}.resolve_integration_secrets", new_callable=AsyncMock) as resolver,
        patch(f"{MOD}.StripeClient", _client_factory(built_with, clients)),
    ):
        resolver.return_value = {"api_key": "sk_tenant_a"}
        service = _service()
        await service.create_payment_intent(
            amount=1200, currency="eur", description="Order 42", idempotency_key="order-42"
        )
        await service.create_payment_intent(amount=500)

    with_key, without_key = (c.v1.payment_intents.create_async for c in clients)
    params, kwargs = with_key.await_args.args[0], with_key.await_args.kwargs
    assert params == {"amount": 1200, "currency": "eur", "description": "Order 42"}
    assert kwargs["options"] == {"idempotency_key": "order-42"}

    params, kwargs = without_key.await_args.args[0], without_key.await_args.kwargs
    assert params == {"amount": 500, "currency": "usd"}  # no description key when absent
    assert kwargs["options"] is None  # no idempotency key → no options


@pytest.mark.asyncio
async def test_not_connected_raises_before_building_a_client() -> None:
    built_with: list[str] = []
    clients: list[MagicMock] = []
    with (
        patch(f"{MOD}.resolve_integration_secrets", new_callable=AsyncMock) as resolver,
        patch(f"{MOD}.StripeClient", _client_factory(built_with, clients)),
    ):
        resolver.return_value = {}
        with pytest.raises(ValueError, match="not connected"):
            await _service().get_customer("cus_1")

    assert built_with == []  # no client is ever built without a key
    assert stripe.api_key is None

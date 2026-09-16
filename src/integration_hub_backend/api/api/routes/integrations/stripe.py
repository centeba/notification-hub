"""Stripe integration - customers, payments, and invoices."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel

from integration_hub_backend.api.api.deps import ApiKeyDep, SessionDep
from integration_hub_backend.api.services.observability_service import ObservabilityService
from integration_hub_backend.api.services.stripe_service import StripeService

router = APIRouter(prefix="/stripe", tags=["integrations"])


class PaymentIntentRequest(BaseModel):
    amount: int
    currency: str = "usd"
    description: str | None = None


@router.get("/customers/{customer_id}")
async def get_stripe_customer(
    customer_id: str, db: SessionDep, api_key: ApiKeyDep
) -> dict[str, Any]:
    """Retrieve a Stripe customer's details (Global)."""
    api_key.require_scope("integrations:stripe")
    service = StripeService(ObservabilityService(db), api_key.company_id)
    return await service.get_customer(customer_id)


@router.post("/payments/intent")
async def create_stripe_payment_intent(
    body: PaymentIntentRequest, db: SessionDep, api_key: ApiKeyDep
) -> dict[str, Any]:
    """Create a new Stripe Payment Intent (Global)."""
    api_key.require_scope("integrations:stripe")
    service = StripeService(ObservabilityService(db), api_key.company_id)
    return await service.create_payment_intent(
        amount=body.amount, currency=body.currency, description=body.description
    )


@router.get("/invoices")
async def list_stripe_invoices(
    db: SessionDep, api_key: ApiKeyDep, limit: int = 10
) -> list[dict[str, Any]]:
    """List recent Stripe invoices (Global)."""
    api_key.require_scope("integrations:stripe")
    service = StripeService(ObservabilityService(db), api_key.company_id)
    return await service.list_invoices(limit=limit)

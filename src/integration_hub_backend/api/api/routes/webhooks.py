"""Webhook endpoint management."""

from __future__ import annotations

import uuid

import structlog
from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select

from integration_hub_backend._platform.ssrf import SsrfError, validate_url
from integration_hub_backend.api.api.deps import CompanyAdminDep, SessionDep
from integration_hub_backend.api.core.security import encrypt_field
from integration_hub_backend.api.models.webhook_endpoint import (
    NotificationWebhookEndpoint,
    WebhookEndpointCreate,
    WebhookEndpointPublic,
    WebhookEndpointsPublic,
    WebhookEndpointUpdate,
)

log = structlog.get_logger(__name__)

router = APIRouter(prefix="/webhooks", tags=["webhooks"])

# ── SSRF Protection ───────────────────────────────────────────────────────────


def _validate_webhook_url(url: str) -> str:
    """Validate a stored webhook-endpoint URL (SSRF prevention). Delegates to the
    shared canonical guard so this service, mit-stack, and the outbound sender
    all enforce the same policy."""
    try:
        validate_url(url)
    except SsrfError as exc:
        raise HTTPException(status_code=400, detail=f"URL blocked: {exc}")
    return url


# ── Routes ────────────────────────────────────────────────────────────────────


@router.get("", response_model=WebhookEndpointsPublic)
async def list_webhooks(
    current_user: CompanyAdminDep,
    db: SessionDep,
) -> WebhookEndpointsPublic:
    if current_user.company_id is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="No company")
    result = await db.execute(
        select(NotificationWebhookEndpoint).where(
            NotificationWebhookEndpoint.company_id == current_user.company_id
        )
    )
    endpoints = list(result.scalars().all())
    return WebhookEndpointsPublic(
        data=[WebhookEndpointPublic.model_validate(e) for e in endpoints],
        count=len(endpoints),
    )


@router.post("", response_model=WebhookEndpointPublic, status_code=status.HTTP_201_CREATED)
async def create_webhook(
    body: WebhookEndpointCreate,
    current_user: CompanyAdminDep,
    db: SessionDep,
) -> WebhookEndpointPublic:
    if current_user.company_id is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="No company")

    # SSRF validation
    _validate_webhook_url(body.url)

    # Encrypt sensitive fields before persisting
    encrypted_headers = None
    if body.headers:
        import json

        encrypted_headers = {"encrypted": encrypt_field(json.dumps(body.headers))}

    encrypted_auth = None
    if body.auth_config:
        import json

        encrypted_auth = {"encrypted": encrypt_field(json.dumps(body.auth_config))}

    endpoint = NotificationWebhookEndpoint(
        company_id=current_user.company_id,
        name=body.name,
        url=body.url,
        http_method=body.http_method,
        headers=encrypted_headers,
        auth_type=body.auth_type,
        auth_config=encrypted_auth,
        timeout_seconds=body.timeout_seconds,
        retry_count=body.retry_count,
    )
    db.add(endpoint)
    await db.commit()
    await db.refresh(endpoint)

    log.info(
        "webhook_endpoint_created",
        endpoint_id=str(endpoint.id),
        company_id=str(current_user.company_id),
        name=endpoint.name,
        url=endpoint.url,
        user_id=str(current_user.id),
    )

    return WebhookEndpointPublic.model_validate(endpoint)


@router.patch("/{endpoint_id}", response_model=WebhookEndpointPublic)
async def update_webhook(
    endpoint_id: uuid.UUID,
    body: WebhookEndpointUpdate,
    current_user: CompanyAdminDep,
    db: SessionDep,
) -> WebhookEndpointPublic:
    if current_user.company_id is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="No company")
    result = await db.execute(
        select(NotificationWebhookEndpoint).where(
            NotificationWebhookEndpoint.id == endpoint_id,
            NotificationWebhookEndpoint.company_id == current_user.company_id,
        )
    )
    endpoint = result.scalar_one_or_none()
    if not endpoint:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Webhook endpoint not found"
        )

    if body.url:
        _validate_webhook_url(body.url)

    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(endpoint, field, value)

    await db.commit()
    await db.refresh(endpoint)

    log.info(
        "webhook_endpoint_updated",
        endpoint_id=str(endpoint.id),
        company_id=str(current_user.company_id),
        name=endpoint.name,
        user_id=str(current_user.id),
    )

    return WebhookEndpointPublic.model_validate(endpoint)


@router.delete("/{endpoint_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_webhook(
    endpoint_id: uuid.UUID,
    current_user: CompanyAdminDep,
    db: SessionDep,
) -> None:
    if current_user.company_id is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="No company")
    result = await db.execute(
        select(NotificationWebhookEndpoint).where(
            NotificationWebhookEndpoint.id == endpoint_id,
            NotificationWebhookEndpoint.company_id == current_user.company_id,
        )
    )
    endpoint = result.scalar_one_or_none()
    if not endpoint:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Webhook endpoint not found"
        )

    endpoint_name = endpoint.name
    await db.delete(endpoint)
    await db.commit()

    log.info(
        "webhook_endpoint_deleted",
        endpoint_id=str(endpoint_id),
        company_id=str(current_user.company_id),
        name=endpoint_name,
        user_id=str(current_user.id),
    )

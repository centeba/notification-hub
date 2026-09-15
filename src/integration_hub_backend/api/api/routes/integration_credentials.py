"""Integration credential management endpoints."""

import uuid
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from integration_hub_backend.api.api.deps import ApiKeyDep, SessionDep
from integration_hub_backend.api.api.routes.integrations_catalog import _CATALOG
from integration_hub_backend.api.crud.integration_credentials import (
    create_credential,
    delete_credential,
    get_decrypted,
    list_credentials,
)
from integration_hub_backend.api.models.integration_credential import (
    VALID_CREDENTIAL_TYPES,
    CredentialCreate,
    CredentialPublic,
    CredentialsPublic,
)
from integration_hub_backend.sentinelbuild_auth import SBUser, get_sb_user

router = APIRouter(prefix="/credentials", tags=["credentials"])

# connector key -> auth type ("api_key" | "oauth2" | "none"), from the
# JWT-readable catalog so this surface can't drift from what the UI lists.
_CONNECTOR_AUTH: dict[str, str] = {e.key: e.auth for e in _CATALOG}

# Observability connectors carry their own credential ``type`` (they map to
# distinct downstream clients); everything else is a generic api_key row.
_CONNECTOR_TYPED = frozenset({"datadog", "splunk", "grafana", "elasticsearch", "kibana"})


def _require_admin(user: SBUser) -> None:
    if not user.is_company_admin_or_above():
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin role required to manage integration credentials",
        )


@router.post("/", response_model=CredentialPublic, status_code=status.HTTP_201_CREATED)
async def create_integration_credential(
    body: CredentialCreate,
    db: SessionDep,
    api_key: ApiKeyDep,
) -> CredentialPublic:
    api_key.require_scope("credentials:write")
    if body.type not in VALID_CREDENTIAL_TYPES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Invalid type '{body.type}'. Valid: {sorted(VALID_CREDENTIAL_TYPES)}",
        )
    cred = await create_credential(
        db,
        company_id=api_key.company_id,
        name=body.name,
        type_=body.type,
        secret_data=body.secret_data,
    )
    return CredentialPublic.model_validate(cred)


@router.get("/", response_model=CredentialsPublic)
async def list_integration_credentials(
    db: SessionDep,
    api_key: ApiKeyDep,
) -> CredentialsPublic:
    api_key.require_scope("credentials:read")
    creds = await list_credentials(db, company_id=api_key.company_id)
    return CredentialsPublic(
        data=[CredentialPublic.model_validate(c) for c in creds],
        count=len(creds),
    )


@router.delete("/{credential_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_integration_credential(
    credential_id: uuid.UUID,
    db: SessionDep,
    api_key: ApiKeyDep,
) -> None:
    api_key.require_scope("credentials:write")
    deleted = await delete_credential(db, credential_id, company_id=api_key.company_id)
    if not deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Credential not found")


class MailboxCredential(BaseModel):
    id: uuid.UUID
    name: str
    provider: str
    email: str | None = None
    created_at: datetime


@router.get("/mailboxes", response_model=list[MailboxCredential])
async def list_mailbox_credentials(
    db: SessionDep,
    current_user: SBUser = Depends(get_sb_user),
) -> list[MailboxCredential]:
    """JWT-authed list of OAuth mailbox credentials.

    The ``oauth_connect`` flow stores Gmail/Outlook accounts as
    ``type='oauth2'`` rows with ``provider`` inside the encrypted blob.
    The frontend Email tab needs to surface them filtered by provider,
    which the api-key-only ``GET /credentials/`` endpoint can't do for
    SBUser-authed callers. This is the JWT-authed counterpart.
    """
    creds = await list_credentials(db, company_id=uuid.UUID(current_user.org_id))
    out: list[MailboxCredential] = []
    for c in creds:
        if c.type != "oauth2":
            continue
        try:
            decrypted = get_decrypted(c)
        except Exception:
            continue
        provider = decrypted.get("provider")
        if provider not in ("gmail", "outlook"):
            continue
        out.append(
            MailboxCredential(
                id=c.id,
                name=c.name,
                provider=provider,
                email=decrypted.get("email"),
                created_at=c.created_at,
            )
        )
    return out


# ── JWT-admin connector connect surface ─────────────────────────────────────
# Human admins manage connector credentials from the chassis Integration Hub
# "Integrations" tab. This is a parallel, JWT+admin-gated surface to the M2M
# (ApiKeyDep) ``POST /credentials/`` above — it never replaces it. Every
# credential created here is tagged with its catalog ``connector`` key so the
# UI can render a per-connector "Connected" badge.


class ConnectorStatus(BaseModel):
    connector: str
    connected: bool
    credential_id: uuid.UUID
    name: str
    created_at: datetime


class ConnectRequest(BaseModel):
    connector: str
    name: str
    secret_data: dict[str, Any]


@router.get("/status", response_model=list[ConnectorStatus])
async def list_connector_status(
    db: SessionDep,
    current_user: SBUser = Depends(get_sb_user),
) -> list[ConnectorStatus]:
    """JWT-authed per-connector connected state for the caller's company.

    Returns one entry per stored credential that carries a ``connector``
    tag (legacy/M2M rows without a tag are omitted). The UI joins this
    against the connector catalog to render badges. No secrets are exposed.
    """
    _require_admin(current_user)
    creds = await list_credentials(db, company_id=uuid.UUID(current_user.org_id))
    out: list[ConnectorStatus] = []
    for c in creds:
        if not c.connector:
            continue
        out.append(
            ConnectorStatus(
                connector=c.connector,
                connected=True,
                credential_id=c.id,
                name=c.name,
                created_at=c.created_at,
            )
        )
    return out


@router.post("/connect", response_model=CredentialPublic, status_code=status.HTTP_201_CREATED)
async def connect_integration(
    body: ConnectRequest,
    db: SessionDep,
    current_user: SBUser = Depends(get_sb_user),
) -> CredentialPublic:
    """JWT-admin: store an API-key credential for a catalog connector.

    OAuth connectors (gmail/outlook) are connected via the ``/oauth/*``
    authorize flow, not here; this endpoint covers the api_key connectors.
    """
    _require_admin(current_user)
    auth = _CONNECTOR_AUTH.get(body.connector)
    if auth is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Unknown connector '{body.connector}'",
        )
    if auth != "api_key":
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                f"Connector '{body.connector}' uses {auth} auth; "
                "use the OAuth connect flow instead of an API key"
            ),
        )
    if not body.secret_data:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="secret_data must not be empty",
        )
    type_ = body.connector if body.connector in _CONNECTOR_TYPED else "api_key"
    cred = await create_credential(
        db,
        company_id=uuid.UUID(current_user.org_id),
        name=body.name or body.connector,
        type_=type_,
        secret_data=body.secret_data,
        connector=body.connector,
    )
    return CredentialPublic.model_validate(cred)


@router.delete("/connect/{credential_id}", status_code=status.HTTP_204_NO_CONTENT)
async def disconnect_integration(
    credential_id: uuid.UUID,
    db: SessionDep,
    current_user: SBUser = Depends(get_sb_user),
) -> None:
    """JWT-admin: remove a stored connector credential (disconnect)."""
    _require_admin(current_user)
    deleted = await delete_credential(db, credential_id, company_id=uuid.UUID(current_user.org_id))
    if not deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Credential not found")

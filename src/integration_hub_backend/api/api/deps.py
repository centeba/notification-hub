"""FastAPI dependency injection: auth, DB session, Redis."""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Annotated, TypeAlias

import redis.asyncio as aioredis
from fastapi import Depends, Header, HTTPException, Request, Security, status
from fastapi.security import APIKeyHeader, HTTPAuthorizationCredentials, HTTPBearer
from smart_llm.current_user import COMPANY_ADMIN_ROLES, authenticate
from smart_llm.current_user import CurrentUser as PlatformUser
from smart_llm.internal_auth import INTERNAL_KEY_HEADER, is_internal_caller, require_internal_key
from sqlalchemy.ext.asyncio import AsyncSession

from integration_hub_backend.api.core.cache import (
    TTL_API_KEY,
    _key_api_key,
    cache_get,
    cache_set,
)
from integration_hub_backend.api.core.config import settings
from integration_hub_backend.api.core.db import (
    get_db,
    set_bypass_rls,
    set_current_org,
)
from integration_hub_backend.api.core.redis import get_redis
from integration_hub_backend.api.core.security import (
    verify_api_key,
    verify_webhook_signature,
)

# ── Inbound webhook HMAC (optional second factor) ─────────────────────────────

WEBHOOK_SIGNATURE_HEADER = "X-Hub-Signature-256"
WEBHOOK_TIMESTAMP_HEADER = "X-Sentinel-Timestamp"


async def optional_webhook_signature(request: Request) -> None:
    """Enforce an inbound-webhook HMAC signature ONLY when `WEBHOOK_SECRET` is
    configured; otherwise a no-op so API-key-only senders are unaffected.

    When enforced: requires ``X-Hub-Signature-256`` over the raw body (constant-
    time compare) and, if the sender includes ``X-Sentinel-Timestamp``, applies
    the SDK's replay-protected scheme + freshness window (see
    core.security.verify_webhook_signature). Rejects missing/invalid/stale
    signatures with 401. Mount alongside the API-key dep on inbound receivers.
    """
    secret = settings.WEBHOOK_SECRET
    if not secret:
        return
    signature = request.headers.get(WEBHOOK_SIGNATURE_HEADER)
    if not signature:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing webhook signature",
        )
    body = await request.body()  # cached by Starlette; the route re-reads safely
    timestamp = request.headers.get(WEBHOOK_TIMESTAMP_HEADER)
    if not verify_webhook_signature(body, secret, signature, timestamp=timestamp):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or stale webhook signature",
        )


# ── DB & Redis ────────────────────────────────────────────────────────────────

SessionDep = Annotated[AsyncSession, Depends(get_db)]
RedisDep = Annotated[aioredis.Redis, Depends(get_redis)]

# ── JWT Auth (tokens issued by User Master) ───────────────────────────────────

bearer_scheme = HTTPBearer(auto_error=False)


# The caller, as the platform's shared current-user contract builds it: ``id``
# (the smart-llm router factories read it), ``company_id``, ``role``, ``email``,
# ``is_platform_admin`` (system_admin | platform_admin) and ``is_company_admin``
# (company_admin | system_admin — platform_admin is a builder role, not a
# company admin).
CurrentUserPayload: TypeAlias = PlatformUser


async def get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
) -> CurrentUserPayload:
    """Verification, revocation and the 401 contract are the shared
    ``smart_llm.current_user.authenticate``; the RLS stamp is this service's."""
    user = await authenticate(credentials.credentials if credentials else None)
    _stamp_tenant(user)  # RLS tenant GUC for this request
    return user


def _stamp_tenant(user: CurrentUserPayload) -> None:
    """Stamp the RLS tenant context (core/db.py) from the resolved identity:
    platform/system admins run the cross-tenant console → bypass; every other
    caller is scoped to their JWT ``company_id`` (a token with no company →
    empty org → fail-closed zero rows)."""
    if user.is_platform_admin:
        set_bypass_rls()
    else:
        set_current_org(user.company_id)


CurrentUser = Annotated[CurrentUserPayload, Depends(get_current_user)]


async def require_platform_admin(current_user: CurrentUser) -> CurrentUserPayload:
    if not current_user.is_platform_admin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Platform admin required")
    return current_user


async def require_company_admin(current_user: CurrentUser) -> CurrentUserPayload:
    if not current_user.is_company_admin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Company admin required")
    return current_user


PlatformAdminDep = Annotated[CurrentUserPayload, Depends(require_platform_admin)]
CompanyAdminDep = Annotated[CurrentUserPayload, Depends(require_company_admin)]

#: Builder surfaces (AI search, agent grants, running write-capable AI tools):
#: company admins plus the platform builder (``platform_admin``), which authors
#: and tests agents and tools but is not a company admin, so it fails
#: ``require_company_admin``.
BUILDER_ROLES = COMPANY_ADMIN_ROLES | {"platform_admin"}


def can_build(user: CurrentUserPayload) -> bool:
    return user.role in BUILDER_ROLES


async def require_builder(current_user: CurrentUser) -> CurrentUserPayload:
    if not can_build(current_user):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Company admin or builder required"
        )
    return current_user


BuilderDep = Annotated[CurrentUserPayload, Depends(require_builder)]

# ── API Key Auth (for event ingestion by external systems) ────────────────────

api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


class ApiKeyContext:
    """Resolved API key with company and scopes."""

    def __init__(self, company_id: uuid.UUID, scopes: list[str]) -> None:
        self.company_id = company_id
        self.scopes = scopes

    def require_scope(self, scope: str) -> None:
        if scope not in self.scopes:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"API key missing required scope: {scope}",
            )


async def get_api_key_context(
    raw_key: Annotated[str | None, Depends(api_key_header)],
    db: SessionDep,
    redis: RedisDep,
) -> ApiKeyContext:
    if not raw_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing X-API-Key header",
        )

    # Extract prefix for cache lookup (format: nhk_<8chars>.<secret>)
    parts = raw_key.split(".")
    if len(parts) != 2:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid API key format"
        )

    prefix = parts[0]
    cache_key = _key_api_key(prefix)

    # Bootstrap read: notification_api_keys is looked up by prefix BEFORE the
    # company is known, so the RLS-scoped query would see zero rows. Bypass RLS
    # for the lookup, then scope the rest of the request to the resolved company
    # (set_current_org below) so downstream tenant-table access is isolated.
    set_bypass_rls()

    cached = await cache_get(redis, cache_key)
    if cached:
        # Cached hit — still verify key hash to prevent token reuse after revocation
        from sqlalchemy import select

        from integration_hub_backend.api.models.api_key import NotificationApiKey

        result = await db.execute(
            select(NotificationApiKey).where(
                NotificationApiKey.key_prefix == prefix,
                NotificationApiKey.is_active == True,  # noqa: E712
            )
        )
        api_key = result.scalar_one_or_none()
    else:
        from sqlalchemy import select

        from integration_hub_backend.api.models.api_key import NotificationApiKey

        result = await db.execute(
            select(NotificationApiKey).where(
                NotificationApiKey.key_prefix == prefix,
                NotificationApiKey.is_active == True,  # noqa: E712
            )
        )
        api_key = result.scalar_one_or_none()

    if api_key is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid API key")

    # Check expiry
    if api_key.expires_at and api_key.expires_at < datetime.now(UTC):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="API key expired")

    # Verify hash (constant-time)
    if not verify_api_key(raw_key, api_key.key_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid API key")

    # Update last_used_at asynchronously (fire and forget via background task)
    from sqlalchemy import update

    await db.execute(
        update(NotificationApiKey)
        .where(NotificationApiKey.id == api_key.id)
        .values(last_used_at=datetime.now(UTC))
    )
    await db.commit()

    # Cache valid result
    await cache_set(
        redis,
        cache_key,
        {"company_id": str(api_key.company_id), "scopes": api_key.scopes},
        TTL_API_KEY,
    )

    # Bootstrap done — scope the rest of the request to the key's company so
    # downstream tenant-table access is RLS-isolated (clears the bypass above).
    set_current_org(api_key.company_id)
    return ApiKeyContext(company_id=api_key.company_id, scopes=api_key.scopes)


ApiKeyDep = Annotated[ApiKeyContext, Depends(get_api_key_context)]


# ── Internal Service Auth ─────────────────────────────────────────────────────
#
# Some routes are not for end users — they're called by sibling services
# (user-master, doc-vault, etc.) over the internal docker network. Those
# requests carry ``X-Internal-Key`` (``INTERNAL_API_KEY``) and
# must NOT be reachable through the external nginx ingress (the
# ``/internal/...`` prefix is dropped at the edge).
#
# Outbound use (the calling side) already exists in
# ``temporal/activities/dispatch.py``; this is the matching inbound guard.


async def require_internal_service(_: None = Depends(require_internal_key)) -> bool:
    """The platform internal key (``X-Internal-Key`` = ``INTERNAL_API_KEY``,
    2.3 Part 3); 500 when unconfigured, 401 otherwise on a wrong/missing key.

    An authenticated sibling service runs cross-tenant, so it bypasses RLS —
    same as require_any_auth's internal branch. Unstamped, a tenant-table read
    returns no rows (e.g. the budget loader would see "no settings" and treat
    it as no cap).
    """
    set_bypass_rls()
    return True


InternalServiceDep = Annotated[bool, Depends(require_internal_service)]


# ── Unified auth (JWT user OR internal service secret) ────────────────────────
#
# Used by routes that must be reachable from both the browser (human admin) and
# from sibling-service Temporal workers (action_node dispatch). The worker sends
# ``X-Internal-Key``; browsers send a JWT.


@dataclass
class AuthContext:
    """Resolved identity for a request that may come from a user or a sibling
    service. ``user`` is ``None`` when ``is_internal`` is ``True``."""

    user: CurrentUserPayload | None
    is_internal: bool


async def require_any_auth(
    creds: Annotated[HTTPAuthorizationCredentials | None, Security(bearer_scheme)],
    x_internal_key: Annotated[str | None, Header(alias=INTERNAL_KEY_HEADER)] = None,
) -> AuthContext:
    """Accept the platform internal key (``X-Internal-Key``) or a normal user
    JWT. Raises 401 if neither matches."""
    if is_internal_caller(x_internal_key):
        set_bypass_rls()  # sibling-service M2M caller runs cross-tenant
        return AuthContext(user=None, is_internal=True)
    if creds is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
            headers={"WWW-Authenticate": "Bearer"},
        )
    token = creds.credentials

    # JWT path — the same shared contract as get_current_user.
    user = await authenticate(token)
    _stamp_tenant(user)  # RLS tenant GUC for this request
    return AuthContext(user=user, is_internal=False)


AnyAuthDep = Annotated[AuthContext, Depends(require_any_auth)]

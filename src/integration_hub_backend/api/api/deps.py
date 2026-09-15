"""FastAPI dependency injection: auth, DB session, Redis."""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Annotated

import jwt
import redis.asyncio as aioredis
from fastapi import Depends, Header, HTTPException, Request, Security, status
from fastapi.security import APIKeyHeader, HTTPAuthorizationCredentials, HTTPBearer
from smart_llm.platform_auth import decode_platform_token
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


class CurrentUserPayload:
    """Decoded JWT payload from User Master."""

    def __init__(
        self,
        user_id: uuid.UUID,
        company_id: uuid.UUID | None,
        role: str,
        email: str,
    ) -> None:
        self.user_id = user_id
        self.company_id = company_id
        self.role = role
        self.email = email

    @property
    def id(self) -> uuid.UUID:
        """Alias for user_id — required by smart-llm router factories."""
        return self.user_id

    @property
    def is_platform_admin(self) -> bool:
        # user-master's ``normalize_role`` rewrites the legacy
        # ``platform_admin`` → ``system_admin`` before signing the JWT,
        # so the tokens we actually receive carry ``system_admin``.
        # Accept both for backwards compat with any pre-normalisation
        # tokens still in the wild.
        return self.role in ("platform_admin", "system_admin")

    @property
    def is_company_admin(self) -> bool:
        return self.role in ("company_admin", "platform_admin", "system_admin")


async def get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
) -> CurrentUserPayload:
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )
    token = credentials.credentials
    try:
        payload = decode_platform_token(token, settings.SECRET_KEY, require=["sub", "exp"])
    except jwt.ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token expired",
            headers={"WWW-Authenticate": "Bearer"},
        )
    except jwt.InvalidTokenError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Reject pre-2FA tokens
    if payload.get("scope") == "pre_2fa":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="2FA verification required",
        )

    company_id_raw = payload.get("company_id")
    user = CurrentUserPayload(
        user_id=uuid.UUID(payload["sub"]),
        company_id=uuid.UUID(company_id_raw) if company_id_raw else None,
        role=payload.get("role", "user"),
        email=payload.get("email", ""),
    )
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
# requests carry ``Authorization: Bearer ${INTERNAL_SERVICE_SECRET}`` and
# must NOT be reachable through the external nginx ingress (the
# ``/internal/...`` prefix is dropped at the edge).
#
# Outbound use (the calling side) already exists in
# ``temporal/activities/dispatch.py``; this is the matching inbound guard.


async def require_internal_service(
    creds: Annotated[HTTPAuthorizationCredentials | None, Security(bearer_scheme)],
    x_internal_key: Annotated[str | None, Header(alias="X-Internal-Key")] = None,
) -> bool:
    """Accept either the canonical ``X-Internal-Key`` header or the legacy
    ``Authorization: Bearer <INTERNAL_SERVICE_SECRET>`` header.

    Phase 1.4 of the architecture assessment consolidates the two M2M
    secrets. New callers should send ``X-Internal-Key`` matching
    ``INTERNAL_API_KEY``; existing Bearer callers continue to work until
    they migrate. Once telemetry shows zero Bearer usage,
    ``INTERNAL_SERVICE_SECRET`` and the Bearer branch can be removed.
    """
    api_key = settings.INTERNAL_API_KEY
    bearer_secret = settings.INTERNAL_SERVICE_SECRET

    # Canonical header check (preferred).
    if api_key and x_internal_key and _consttime_eq(x_internal_key, api_key):
        return True

    # Transitional Bearer alias.
    if bearer_secret and creds is not None and _consttime_eq(creds.credentials, bearer_secret):
        return True

    if not api_key and not bearer_secret:
        # Hard-fail rather than fail-open: an unset secret in prod is a
        # misconfiguration that would otherwise allow unauthenticated
        # access to internal endpoints.
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="No internal-service secret configured (INTERNAL_API_KEY / INTERNAL_SERVICE_SECRET)",
        )

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid internal service credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )


def _consttime_eq(a: str, b: str) -> bool:
    # Avoid leaking length / prefix via early-return comparison.
    import secrets as _secrets

    return _secrets.compare_digest(a, b)


InternalServiceDep = Annotated[bool, Depends(require_internal_service)]


# ── Unified auth (JWT user OR internal service secret) ────────────────────────
#
# Used by routes that must be reachable from both the browser (human admin) and
# from sibling-service Temporal workers (action_node dispatch). The worker sends
# ``Authorization: Bearer ${INTERNAL_SERVICE_SECRET}``; browsers send a JWT.


@dataclass
class AuthContext:
    """Resolved identity for a request that may come from a user or a sibling
    service. ``user`` is ``None`` when ``is_internal`` is ``True``."""

    user: CurrentUserPayload | None
    is_internal: bool


async def require_any_auth(
    creds: Annotated[HTTPAuthorizationCredentials | None, Security(bearer_scheme)],
) -> AuthContext:
    """Accept either a raw ``INTERNAL_SERVICE_SECRET`` bearer token or a
    normal user JWT. Raises 401 if neither matches."""
    if creds is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
            headers={"WWW-Authenticate": "Bearer"},
        )
    token = creds.credentials

    # Internal-service path: raw secret match (not a JWT). Accepts either
    # the canonical INTERNAL_API_KEY or the transitional INTERNAL_SERVICE_SECRET
    # alias — same dual-check as require_internal_service above. Callers
    # (e.g. the SDK's SmartLlmInvokeClient) carry their own INTERNAL_SERVICE_SECRET
    # env var as the bearer token, which in practice is provisioned to match
    # this service's INTERNAL_API_KEY value, not its own (usually-unset,
    # randomly-defaulted) INTERNAL_SERVICE_SECRET.
    if settings.INTERNAL_API_KEY and _consttime_eq(token, settings.INTERNAL_API_KEY):
        set_bypass_rls()  # sibling-service M2M caller runs cross-tenant
        return AuthContext(user=None, is_internal=True)
    if settings.INTERNAL_SERVICE_SECRET and _consttime_eq(token, settings.INTERNAL_SERVICE_SECRET):
        set_bypass_rls()  # sibling-service M2M caller runs cross-tenant
        return AuthContext(user=None, is_internal=True)

    # JWT path — same decode logic as get_current_user.
    try:
        payload = decode_platform_token(token, settings.SECRET_KEY, require=["sub", "exp"])
    except jwt.ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token expired",
            headers={"WWW-Authenticate": "Bearer"},
        )
    except jwt.InvalidTokenError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if payload.get("scope") == "pre_2fa":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="2FA verification required",
        )

    company_id_raw = payload.get("company_id")
    user = CurrentUserPayload(
        user_id=uuid.UUID(payload["sub"]),
        company_id=uuid.UUID(company_id_raw) if company_id_raw else None,
        role=payload.get("role", "user"),
        email=payload.get("email", ""),
    )
    _stamp_tenant(user)  # RLS tenant GUC for this request
    return AuthContext(user=user, is_internal=False)


AnyAuthDep = Annotated[AuthContext, Depends(require_any_auth)]

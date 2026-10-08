"""
SentinelBuild shared JWT validation for integration-hub.

Validates tokens issued by User Master against the same ``settings.SECRET_KEY``
as ``api.api.deps.get_current_user`` (one secret source for both verifiers),
checks the shared revocation denylist and stamps the RLS tenant context.
Provides FastAPI dependency `get_sb_user` that returns a SBUser dataclass.
"""

from __future__ import annotations

from dataclasses import dataclass

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from smart_llm.platform_auth import decode_platform_token, platform_auth_configured
from smart_llm.token_revocation import token_is_revoked

from integration_hub_backend.api.core.config import settings
from integration_hub_backend.api.core.db import set_bypass_rls, set_current_org

_bearer = HTTPBearer(auto_error=True)

ROLE_SYSTEM_ADMIN = "system_admin"
ROLE_PLATFORM_ADMIN = "platform_admin"
ROLE_COMPANY_ADMIN = "company_admin"
ROLE_MEMBER = "member"
ROLE_VIEWER = "viewer"


@dataclass
class SBUser:
    user_id: str
    org_id: str
    role: str
    email: str

    def is_system_admin(self) -> bool:
        return self.role in (ROLE_SYSTEM_ADMIN, ROLE_PLATFORM_ADMIN)

    def is_company_admin_or_above(self) -> bool:
        return self.role in (ROLE_SYSTEM_ADMIN, ROLE_PLATFORM_ADMIN, ROLE_COMPANY_ADMIN)

    def can_author(self) -> bool:
        return self.role != ROLE_VIEWER


async def get_sb_user(
    credentials: HTTPAuthorizationCredentials = Depends(_bearer),
) -> SBUser:
    token = credentials.credentials
    # Fail closed if no verification key is configured at all (neither the
    # HS256 shared secret nor the RS256 public key) rather than silently
    # accepting forged tokens.
    secret = settings.SECRET_KEY
    if not secret and not platform_auth_configured():
        raise HTTPException(status_code=500, detail="Server misconfigured: no JWT key")
    try:
        payload = decode_platform_token(token, secret)
    except jwt.InvalidTokenError:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid token",
            headers={"X-Auth-Error": "token_expired"},
        )
    # Gate 3: a token revoked before its exp (logout / password change) is
    # refused. No-op unless TOKEN_REVOCATION_REDIS_URL is configured.
    if await token_is_revoked(payload):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Token has been revoked"
        )

    if payload.get("scope") == "pre_2fa":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="2FA verification required"
        )

    user_id = payload.get("sub")
    org_id = payload.get("org") or payload.get("company_id")
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid token claims",
            headers={"X-Auth-Error": "token_expired"},
        )

    user = SBUser(
        user_id=user_id,
        org_id=org_id or "",
        role=payload.get("role", ROLE_MEMBER),
        email=payload.get("email", ""),
    )
    # RLS tenant context, same policy as deps._stamp_tenant: system admins run
    # the cross-tenant console; everyone else is scoped to their org (no org →
    # empty → fail-closed zero rows).
    if user.is_system_admin():
        set_bypass_rls()
    else:
        set_current_org(user.org_id or None)
    return user


SBUserDep = Depends(get_sb_user)

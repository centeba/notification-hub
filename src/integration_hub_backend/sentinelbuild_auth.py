"""
SentinelBuild shared JWT validation for integration-hub.

Validates tokens issued by User Master (HS256, SECRET_KEY).
Provides FastAPI dependency `get_sb_user` that returns a SBUser dataclass.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from smart_llm.platform_auth import decode_platform_token, platform_auth_configured

_bearer = HTTPBearer(auto_error=True)
_SECRET = os.environ.get("SHARED_SECRET_KEY", "")

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
    if not _SECRET and not platform_auth_configured():
        raise HTTPException(status_code=500, detail="Server misconfigured: no JWT key")
    try:
        payload = decode_platform_token(token, _SECRET)
    except jwt.InvalidTokenError:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid token",
            headers={"X-Auth-Error": "token_expired"},
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

    return SBUser(
        user_id=user_id,
        org_id=org_id or "",
        role=payload.get("role", ROLE_MEMBER),
        email=payload.get("email", ""),
    )


SBUserDep = Depends(get_sb_user)

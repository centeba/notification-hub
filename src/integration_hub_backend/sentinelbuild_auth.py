"""
SentinelBuild JWT authentication for integration-hub's Connect-UI routes.

Verification, revocation and the 401 contract are the platform's shared
``smart_llm.current_user.authenticate`` (RS256, user-master's public key), the
same as ``api.api.deps.get_current_user``. This module keeps the ``SBUser`` shape
(string ids, used by the credential and OAuth-connect routes) and stamps the RLS
tenant context.
"""

from dataclasses import dataclass

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from smart_llm.current_user import COMPANY_ADMIN_ROLES, PLATFORM_ADMIN_ROLES, authenticate

from integration_hub_backend.api.core.db import set_bypass_rls, set_current_org

# auto_error=False: a missing header gets the shared 401 contract.
_bearer = HTTPBearer(auto_error=False)

ROLE_VIEWER = "viewer"


@dataclass
class SBUser:
    user_id: str
    org_id: str
    role: str
    email: str

    def is_system_admin(self) -> bool:
        return self.role in PLATFORM_ADMIN_ROLES

    def is_company_admin_or_above(self) -> bool:
        return self.role in COMPANY_ADMIN_ROLES

    def can_author(self) -> bool:
        return self.role != ROLE_VIEWER


async def get_sb_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> SBUser:
    user = await authenticate(credentials.credentials if credentials else None)
    # RLS tenant context, same policy as deps._stamp_tenant: system admins run
    # the cross-tenant console; everyone else is scoped to their org (no org →
    # fail-closed zero rows).
    if user.is_platform_admin:
        set_bypass_rls()
    else:
        set_current_org(user.company_id)
    return SBUser(
        user_id=str(user.user_id),
        org_id=str(user.company_id) if user.company_id else "",
        role=user.role,
        email=user.email,
    )


SBUserDep = Depends(get_sb_user)

"""integration-hub's main verifier (get_current_user, require_any_auth and the
WebSocket resolver) on the platform's shared current-user contract (2.1)."""

import time
import uuid

import jwt
import pytest
from fastapi import HTTPException
from fastapi.security import HTTPAuthorizationCredentials

from integration_hub_backend.api.api import deps
from integration_hub_backend.api.api.ws_auth import resolve_token_for_stream
from integration_hub_backend.api.core import db
from tests.conftest import JWT_KEY

USER = uuid.uuid4()
COMPANY = uuid.uuid4()


def _token(**claims: object) -> str:
    payload: dict[str, object] = {
        "sub": str(USER),
        "scope": "full",
        "exp": int(time.time()) + 300,
        "company_id": str(COMPANY),
        "role": "member",
    }
    payload.update(claims)
    return jwt.encode(
        {k: v for k, v in payload.items() if v is not None}, JWT_KEY, algorithm="RS256"
    )


def _creds(token: str) -> HTTPAuthorizationCredentials:
    return HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)


async def test_get_current_user_reads_org_when_company_id_is_absent() -> None:
    db.reset_tenant_context()
    user = await deps.get_current_user(_creds(_token(company_id=None, org=str(COMPANY))))
    assert user.company_id == COMPANY
    assert db._current_org.get() == str(COMPANY)


async def test_expired_token_is_401_with_x_auth_error() -> None:
    with pytest.raises(HTTPException) as exc:
        await deps.get_current_user(_creds(_token(exp=int(time.time()) - 10)))
    assert exc.value.status_code == 401
    assert exc.value.headers is not None
    assert exc.value.headers["X-Auth-Error"] == "token_expired"


async def test_missing_token_is_401() -> None:
    with pytest.raises(HTTPException) as exc:
        await deps.get_current_user(None)
    assert exc.value.status_code == 401
    assert exc.value.headers == {"WWW-Authenticate": "Bearer"}


async def test_router_factory_contract() -> None:
    # The smart-llm agents / skills / usage routers read .id and .company_id.
    user = await deps.get_current_user(_creds(_token()))
    assert user.id == USER
    assert user.company_id == COMPANY


@pytest.mark.parametrize(
    ("role", "platform", "company"),
    [
        ("system_admin", True, True),
        ("platform_admin", True, False),
        ("company_admin", False, True),
        ("member", False, False),
    ],
)
async def test_admin_dependencies_follow_the_platform_rules(
    role: str, platform: bool, company: bool
) -> None:
    user = await deps.get_current_user(_creds(_token(role=role)))
    if company:
        assert await deps.require_company_admin(user) is user
    else:
        with pytest.raises(HTTPException) as exc:
            await deps.require_company_admin(user)
        assert exc.value.status_code == 403
    if platform:
        assert await deps.require_platform_admin(user) is user
    else:
        with pytest.raises(HTTPException):
            await deps.require_platform_admin(user)


async def test_require_any_auth_jwt_path_uses_the_shared_contract() -> None:
    ctx = await deps.require_any_auth(_creds(_token(company_id=None, cid=str(COMPANY))))
    assert ctx.is_internal is False
    assert ctx.user is not None and ctx.user.company_id == COMPANY
    with pytest.raises(HTTPException) as exc:
        await deps.require_any_auth(_creds("not-a-jwt"))
    assert exc.value.status_code == 401


async def test_ws_resolver_returns_none_on_any_failure_and_stamps_on_success() -> None:
    assert await resolve_token_for_stream("not-a-jwt") is None
    assert await resolve_token_for_stream(_token(exp=int(time.time()) - 10)) is None
    assert await resolve_token_for_stream(_token(scope="pre_2fa")) is None
    db.reset_tenant_context()
    user = await resolve_token_for_stream(_token())
    assert user is not None and user.user_id == USER
    assert db._current_org.get() == str(COMPANY)


@pytest.mark.parametrize(
    ("role", "allowed"),
    [
        ("system_admin", True),
        ("company_admin", True),
        ("platform_admin", True),
        ("member", False),
        ("viewer", False),
    ],
)
async def test_builder_routes_admit_company_admins_and_the_platform_builder(
    role: str, allowed: bool
) -> None:
    # AI search, agent grants and write-capable AI tools stay open to builders.
    user = await deps.get_current_user(_creds(_token(role=role)))
    assert deps.can_build(user) is allowed
    if allowed:
        assert await deps.require_builder(user) is user
    else:
        with pytest.raises(HTTPException) as exc:
            await deps.require_builder(user)
        assert exc.value.status_code == 403

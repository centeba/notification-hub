"""``get_sb_user`` (the Connect-UI verifier) verifies like
``deps.get_current_user`` (RS256, user-master's public key), consults the
revocation denylist and stamps the RLS tenant."""

import uuid

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import HTTPException
from fastapi.security import HTTPAuthorizationCredentials
from smart_llm import current_user

from integration_hub_backend import sentinelbuild_auth
from integration_hub_backend.api.api import deps
from integration_hub_backend.api.core import db
from integration_hub_backend.api.core.config import Settings
from tests.conftest import JWT_KEY

USER_ID = str(uuid.uuid4())
ORG_ID = str(uuid.uuid4())


def _token(key: rsa.RSAPrivateKey = JWT_KEY, **claims: object) -> str:
    payload: dict[str, object] = {
        "sub": USER_ID,
        "org": ORG_ID,
        "company_id": ORG_ID,
        "role": "member",
        "exp": 9999999999,
        "scope": "full",
        "jti": uuid.uuid4().hex,
    }
    payload.update(claims)
    return jwt.encode(payload, key, algorithm="RS256")


def _creds(token: str) -> HTTPAuthorizationCredentials:
    return HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)


# ── settings ─────────────────────────────────────────────────────────────────


def test_unset_llm_encryption_key_refused_in_production() -> None:
    # Stored LLM API keys used to fall back to a key derived from the JWT
    # secret; with that secret gone (2.3) the key must be configured.
    with pytest.raises(ValueError, match="LLM_ENCRYPTION_KEY"):
        Settings(
            LLM_ENCRYPTION_KEY="",
            INTERNAL_API_KEY="x",
            FIELD_ENCRYPTION_KEY="x",
            POSTGRES_PASSWORD="x",  # keep the placeholder guard (#211) out of this test
            ENVIRONMENT="production",
        )


async def test_get_sb_user_verifies_rs256() -> None:
    user = await sentinelbuild_auth.get_sb_user(_creds(_token()))
    assert user.user_id == USER_ID
    assert user.org_id == ORG_ID


async def test_get_sb_user_rejects_token_signed_with_other_key() -> None:
    other = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    with pytest.raises(HTTPException) as exc:
        await sentinelbuild_auth.get_sb_user(_creds(_token(key=other)))
    # Platform contract (2.1): every token failure is 401 + WWW-Authenticate.
    assert exc.value.status_code == 401
    assert exc.value.headers == {"WWW-Authenticate": "Bearer"}


async def test_get_sb_user_missing_token_is_401() -> None:
    with pytest.raises(HTTPException) as exc:
        await sentinelbuild_auth.get_sb_user(None)
    assert exc.value.status_code == 401


async def test_get_sb_user_expired_token_flags_expiry() -> None:
    with pytest.raises(HTTPException) as exc:
        await sentinelbuild_auth.get_sb_user(_creds(_token(exp=1)))
    assert exc.value.status_code == 401
    assert exc.value.headers is not None
    assert exc.value.headers["X-Auth-Error"] == "token_expired"


# ── revocation ───────────────────────────────────────────────────────────────


async def _revoked(_payload: dict[str, object]) -> bool:
    return True


async def test_get_sb_user_rejects_revoked_token(monkeypatch: pytest.MonkeyPatch) -> None:
    # Revocation is checked by the shared authenticate().
    monkeypatch.setattr(current_user, "token_is_revoked", _revoked)
    with pytest.raises(HTTPException) as exc:
        await sentinelbuild_auth.get_sb_user(_creds(_token()))
    assert exc.value.status_code == 401


async def test_get_current_user_rejects_revoked_token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(current_user, "token_is_revoked", _revoked)
    with pytest.raises(HTTPException) as exc:
        await deps.get_current_user(_creds(_token()))
    assert exc.value.status_code == 401


async def test_require_any_auth_rejects_revoked_token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(current_user, "token_is_revoked", _revoked)
    with pytest.raises(HTTPException) as exc:
        await deps.require_any_auth(_creds(_token()))
    assert exc.value.status_code == 401


# ── tenant stamping ──────────────────────────────────────────────────────────


async def test_get_sb_user_stamps_tenant_for_member() -> None:
    db.reset_tenant_context()
    await sentinelbuild_auth.get_sb_user(_creds(_token()))
    assert db._current_org.get() == ORG_ID
    assert db._bypass_rls.get() is False


async def test_get_sb_user_bypasses_rls_for_system_admin() -> None:
    db.reset_tenant_context()
    await sentinelbuild_auth.get_sb_user(_creds(_token(role="system_admin")))
    assert db._bypass_rls.get() is True


async def test_get_sb_user_platform_admin_bypasses_rls_but_is_not_company_admin() -> None:
    db.reset_tenant_context()
    user = await sentinelbuild_auth.get_sb_user(_creds(_token(role="platform_admin")))
    assert db._bypass_rls.get() is True
    # platform_admin is a builder role: it no longer manages a company's
    # integration credentials (the agreed 2.1 admin rule).
    assert user.is_company_admin_or_above() is False

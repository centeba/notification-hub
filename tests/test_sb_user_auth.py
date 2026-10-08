"""``get_sb_user`` (the Connect-UI verifier) shares one JWT secret with
``deps.get_current_user``, consults the revocation denylist and stamps the RLS
tenant — and an unset secret stays unset (no random per-process fill)."""

from __future__ import annotations

import uuid

import jwt
import pytest
from fastapi import HTTPException
from fastapi.security import HTTPAuthorizationCredentials

from integration_hub_backend import sentinelbuild_auth
from integration_hub_backend.api.api import deps
from integration_hub_backend.api.core import db
from integration_hub_backend.api.core.config import Settings, settings

USER_ID = str(uuid.uuid4())
ORG_ID = str(uuid.uuid4())


def _token(secret: str = settings.SECRET_KEY, **claims: object) -> str:
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
    return jwt.encode(payload, secret, algorithm="HS256")


def _creds(token: str) -> HTTPAuthorizationCredentials:
    return HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)


# ── one secret source ────────────────────────────────────────────────────────


def test_shared_secret_key_resolves_onto_secret_key() -> None:
    s = Settings(SECRET_KEY="", SHARED_SECRET_KEY="platform-wide", ENVIRONMENT="local")
    assert s.SECRET_KEY == "platform-wide"


def test_unset_secret_stays_empty_outside_production() -> None:
    s = Settings(SECRET_KEY="", SHARED_SECRET_KEY="", ENVIRONMENT="local")
    assert s.SECRET_KEY == ""


def test_unset_secret_refused_in_production() -> None:
    with pytest.raises(ValueError, match="SECRET_KEY"):
        Settings(
            SECRET_KEY="",
            SHARED_SECRET_KEY="",
            INTERNAL_SERVICE_SECRET="x",
            FIELD_ENCRYPTION_KEY="x",
            ENVIRONMENT="production",
        )


async def test_get_sb_user_verifies_with_settings_secret() -> None:
    user = await sentinelbuild_auth.get_sb_user(_creds(_token()))
    assert user.user_id == USER_ID
    assert user.org_id == ORG_ID


async def test_get_sb_user_rejects_token_signed_with_other_secret() -> None:
    with pytest.raises(HTTPException) as exc:
        await sentinelbuild_auth.get_sb_user(_creds(_token(secret="not-the-platform-key")))
    assert exc.value.status_code == 403


# ── revocation ───────────────────────────────────────────────────────────────


async def _revoked(_payload: dict[str, object]) -> bool:
    return True


async def test_get_sb_user_rejects_revoked_token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sentinelbuild_auth, "token_is_revoked", _revoked)
    with pytest.raises(HTTPException) as exc:
        await sentinelbuild_auth.get_sb_user(_creds(_token()))
    assert exc.value.status_code == 401


async def test_get_current_user_rejects_revoked_token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(deps, "token_is_revoked", _revoked)
    with pytest.raises(HTTPException) as exc:
        await deps.get_current_user(_creds(_token()))
    assert exc.value.status_code == 401


async def test_require_any_auth_rejects_revoked_token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(deps, "token_is_revoked", _revoked)
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

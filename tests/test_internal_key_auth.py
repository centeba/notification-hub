"""integration-hub's internal-auth verifiers accept only the platform internal
key (X-Internal-Key = INTERNAL_API_KEY, 2.3 Part 3). The retired Bearer
INTERNAL_SERVICE_SECRET alias, and a Bearer copy of the key, are rejected."""

import pytest
from fastapi import APIRouter, FastAPI, HTTPException
from fastapi.security import HTTPAuthorizationCredentials
from fastapi.testclient import TestClient
from smart_llm.internal_auth import require_internal_key

from integration_hub_backend.api.api import deps
from integration_hub_backend.email.api.routes import send as email_send
from integration_hub_backend.sms.api.routes import send as sms_send
from integration_hub_backend.webhook.api.routes import send as webhook_send

KEY = "platform-internal-key-for-tests-000000"


def _bearer(token: str) -> HTTPAuthorizationCredentials:
    return HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)


@pytest.fixture(autouse=True)
def _keys(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("INTERNAL_API_KEY", KEY)
    monkeypatch.setattr(deps.settings, "INTERNAL_API_KEY", KEY)
    monkeypatch.setattr(deps, "set_bypass_rls", lambda: None)


# ── the main API's dependencies ──────────────────────────────────────────────


@pytest.mark.parametrize(
    ("headers", "status"),
    [
        ({"X-Internal-Key": KEY}, 200),
        ({"X-Internal-Key": "wrong"}, 401),
        ({}, 401),
        # Neither the retired secret's Bearer alias nor a Bearer copy of the key.
        ({"Authorization": f"Bearer {KEY}"}, 401),
    ],
)
def test_require_internal_service(headers: dict[str, str], status: int) -> None:
    app = FastAPI()

    @app.get("/probe")
    async def _probe(_: deps.InternalServiceDep) -> dict[str, bool]:
        return {"ok": True}

    assert TestClient(app).get("/probe", headers=headers).status_code == status


async def test_require_any_auth_accepts_the_header_without_a_bearer() -> None:
    ctx = await deps.require_any_auth(None, KEY)
    assert ctx.is_internal and ctx.user is None


async def test_require_any_auth_without_credentials_is_401() -> None:
    with pytest.raises(HTTPException) as exc:
        await deps.require_any_auth(None, "wrong")
    assert exc.value.status_code == 401


async def test_require_any_auth_no_longer_takes_the_key_as_a_bearer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _not_a_jwt(token: str) -> None:
        raise HTTPException(status_code=401, detail="Invalid token")

    monkeypatch.setattr(deps, "authenticate", _not_a_jwt)
    with pytest.raises(HTTPException) as exc:
        await deps.require_any_auth(_bearer(KEY), None)
    assert exc.value.status_code == 401


# ── the email / sms / webhook processes ───────────────────────────────────────


@pytest.mark.parametrize(
    "router",
    [email_send.router, sms_send.router, webhook_send.router],
    ids=["email", "sms", "webhook"],
)
def test_send_routes_require_the_internal_key(router: APIRouter) -> None:
    route = next(r for r in router.routes if getattr(r, "path", None) == "/send")
    calls = [d.call for d in route.dependant.dependencies]  # type: ignore[attr-defined]
    assert require_internal_key in calls

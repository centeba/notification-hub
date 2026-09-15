"""JWT-admin connector credential management.

Covers the chassis Integration Hub "connect a connector" surface added on
top of the existing M2M ``/credentials`` routes:

  * ``POST   /credentials/connect``        — admin-gated create, connector-tagged
  * ``GET    /credentials/status``         — per-connector connected state
  * ``DELETE /credentials/connect/{id}``   — admin-gated disconnect

The route handlers are plain async functions, so we call them directly with
an in-memory SQLite session and a constructed ``SBUser`` rather than going
through TestClient (no event-loop juggling, same coverage).
"""

import uuid

import pytest
import pytest_asyncio
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from integration_hub_backend.api.api.routes.integration_credentials import (
    ConnectRequest,
    connect_integration,
    disconnect_integration,
    list_connector_status,
)
from integration_hub_backend.api.core.db import Base
from integration_hub_backend.api.crud.integration_credentials import (
    create_credential,
    get_decrypted,
    list_credentials,
)
from integration_hub_backend.sentinelbuild_auth import SBUser

DATABASE_URL = "sqlite+aiosqlite:///:memory:"


@pytest_asyncio.fixture
async def db():
    engine = create_async_engine(DATABASE_URL)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    Session = async_sessionmaker(engine, expire_on_commit=False)
    async with Session() as session:
        yield session
    await engine.dispose()


def _admin(org_id: str) -> SBUser:
    return SBUser(
        user_id=str(uuid.uuid4()), org_id=org_id, role="company_admin", email="admin@acme.test"
    )


def _member(org_id: str) -> SBUser:
    return SBUser(user_id=str(uuid.uuid4()), org_id=org_id, role="member", email="member@acme.test")


# ── CRUD-level: connector tagging + encryption + isolation ───────────────────


@pytest.mark.asyncio
async def test_create_credential_tags_connector_and_encrypts(db):
    company = uuid.uuid4()
    cred = await create_credential(
        db,
        company_id=company,
        name="Prod Stripe",
        type_="api_key",
        secret_data={"api_key": "sk_live_secret"},
        connector="stripe",
    )
    assert cred.connector == "stripe"
    # Secret is encrypted at rest — plaintext must not appear in the column.
    assert "sk_live_secret" not in cred.encrypted_data
    # …but round-trips through the decrypt helper.
    assert get_decrypted(cred)["api_key"] == "sk_live_secret"


@pytest.mark.asyncio
async def test_list_credentials_connector_filter_and_tenant_isolation(db):
    org_a, org_b = uuid.uuid4(), uuid.uuid4()
    await create_credential(
        db,
        company_id=org_a,
        name="a-stripe",
        type_="api_key",
        secret_data={"k": "1"},
        connector="stripe",
    )
    await create_credential(
        db,
        company_id=org_a,
        name="a-datadog",
        type_="datadog",
        secret_data={"k": "2"},
        connector="datadog",
    )
    await create_credential(
        db,
        company_id=org_b,
        name="b-stripe",
        type_="api_key",
        secret_data={"k": "3"},
        connector="stripe",
    )

    # connector filter scopes to one connector within the org
    only_stripe = await list_credentials(db, company_id=org_a, connector="stripe")
    assert [c.name for c in only_stripe] == ["a-stripe"]

    # no filter → both of org_a's rows, none of org_b's
    all_a = await list_credentials(db, company_id=org_a)
    assert {c.name for c in all_a} == {"a-stripe", "a-datadog"}
    assert all(c.company_id == org_a for c in all_a)


# ── Route-level: admin gating + validation + status/disconnect ───────────────


@pytest.mark.asyncio
async def test_connect_as_admin_creates_tagged_row(db):
    org = uuid.uuid4()
    body = ConnectRequest(connector="stripe", name="Prod", secret_data={"api_key": "sk_live_x"})
    out = await connect_integration(body, db, _admin(str(org)))
    assert out.connector == "stripe"
    rows = await list_credentials(db, company_id=org, connector="stripe")
    assert len(rows) == 1 and get_decrypted(rows[0])["api_key"] == "sk_live_x"


@pytest.mark.asyncio
async def test_connect_as_member_is_forbidden(db):
    body = ConnectRequest(connector="stripe", name="x", secret_data={"api_key": "k"})
    with pytest.raises(HTTPException) as exc:
        await connect_integration(body, db, _member(str(uuid.uuid4())))
    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_connect_unknown_connector_rejected(db):
    body = ConnectRequest(connector="bogus", name="x", secret_data={"api_key": "k"})
    with pytest.raises(HTTPException) as exc:
        await connect_integration(body, db, _admin(str(uuid.uuid4())))
    assert exc.value.status_code == 422


@pytest.mark.asyncio
async def test_connect_oauth_connector_rejected_for_api_key_path(db):
    # gmail is oauth2 in the catalog — must go through the /oauth flow.
    body = ConnectRequest(connector="gmail", name="x", secret_data={"api_key": "k"})
    with pytest.raises(HTTPException) as exc:
        await connect_integration(body, db, _admin(str(uuid.uuid4())))
    assert exc.value.status_code == 422


@pytest.mark.asyncio
async def test_status_reflects_connected_then_disconnect(db):
    org = uuid.uuid4()
    admin = _admin(str(org))
    created = await connect_integration(
        ConnectRequest(connector="stripe", name="Prod", secret_data={"api_key": "k"}),
        db,
        admin,
    )

    status_rows = await list_connector_status(db, admin)
    assert {s.connector for s in status_rows} == {"stripe"}
    assert all(s.connected for s in status_rows)

    await disconnect_integration(created.id, db, admin)
    assert await list_connector_status(db, admin) == []


@pytest.mark.asyncio
async def test_status_omits_untagged_legacy_rows(db):
    org = uuid.uuid4()
    # A legacy/M2M row with no connector tag must not appear in status.
    await create_credential(
        db, company_id=org, name="legacy", type_="api_key", secret_data={"k": "1"}, connector=None
    )
    assert await list_connector_status(db, _admin(str(org))) == []


@pytest.mark.asyncio
async def test_disconnect_other_tenant_row_is_not_found(db):
    org_a, org_b = uuid.uuid4(), uuid.uuid4()
    cred = await create_credential(
        db, company_id=org_a, name="a", type_="api_key", secret_data={"k": "1"}, connector="stripe"
    )
    with pytest.raises(HTTPException) as exc:
        await disconnect_integration(cred.id, db, _admin(str(org_b)))
    assert exc.value.status_code == 404

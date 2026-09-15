"""GDPR right-to-erasure — integration-hub notification PII (SB-17).

Deletes the subject's device tokens + notification preferences and anonymizes
their delivery-log audit rows in place. Self-contained: it creates only the
three PII tables on an in-memory SQLite (swapping the Postgres ``UUID`` type for
the native one so aiosqlite round-trips), and overrides the shared internal-key
gate (its 401 behavior is the same code exercised in the sibling services).
"""

import uuid

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import Uuid, select
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from integration_hub_backend.api.api.deps import get_db, require_internal_service
from integration_hub_backend.api.api.routes.admin import gdpr
from integration_hub_backend.api.core.db import Base
from integration_hub_backend.api.models.delivery_log import NotificationDeliveryLog
from integration_hub_backend.api.models.device_token import DeviceToken
from integration_hub_backend.api.models.preference import NotificationPreference

_TABLES = [
    DeviceToken.__table__,
    NotificationPreference.__table__,
    NotificationDeliveryLog.__table__,
]

# aiosqlite mishandles the postgresql UUID result processor — normalize to the
# native Uuid type on these three tables for the test run.
for _t in _TABLES:
    for _col in _t.columns:
        if isinstance(_col.type, PGUUID):
            _col.type = Uuid()

_URL = "/internal/gdpr/erase-subject"


@pytest_asyncio.fixture
async def client():
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.run_sync(lambda c: Base.metadata.create_all(c, tables=_TABLES))
    factory = async_sessionmaker(engine, expire_on_commit=False)

    async def _override_get_db():
        async with factory() as session:
            yield session

    app = FastAPI()
    app.include_router(gdpr.router)
    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[require_internal_service] = lambda: True

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        ac._factory = factory  # type: ignore[attr-defined]  # expose for assertions
        yield ac
    await engine.dispose()


async def _seed(factory, company, subject, other):
    push_a, push_b = "push-tok-a", "push-tok-b"  # via vars → not flagged as secrets
    async with factory() as s:
        s.add_all(
            [
                DeviceToken(user_id=subject, company_id=company, platform="fcm", token=push_a),
                DeviceToken(user_id=other, company_id=company, platform="fcm", token=push_b),
                NotificationPreference(
                    user_id=subject, company_id=company, channel_id=uuid.uuid4()
                ),
                NotificationPreference(user_id=None, company_id=company, channel_id=uuid.uuid4()),
                NotificationDeliveryLog(
                    event_type="alert",
                    channel="email",
                    recipient_user_id=subject,
                    recipient_contact="enc:victim@example.com",
                    event_payload={"pii": "x"},
                ),
                NotificationDeliveryLog(
                    event_type="alert",
                    channel="email",
                    recipient_user_id=other,
                    recipient_contact="enc:keep@example.com",
                    event_payload={"ok": "y"},
                ),
            ]
        )
        await s.commit()


@pytest.mark.asyncio
async def test_erase_removes_subject_pii_only(client):
    company, subject, other = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    await _seed(client._factory, company, subject, other)

    resp = await client.post(_URL, json={"user_id": str(subject)})
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["service"] == "integration-hub"
    assert data["found"] is True
    assert data["rows_affected"] == {
        "device_tokens_deleted": 1,
        "notification_preferences_deleted": 1,
        "delivery_logs_anonymized": 1,
    }

    async with client._factory() as s:
        tokens = (await s.execute(select(DeviceToken))).scalars().all()
        assert [t.user_id for t in tokens] == [other]  # subject's token deleted

        prefs = (await s.execute(select(NotificationPreference))).scalars().all()
        # subject's pref deleted; the company-default (user_id NULL) is preserved
        assert [p.user_id for p in prefs] == [None]

        rows = (await s.execute(select(NotificationDeliveryLog))).scalars().all()
        logs = {log.recipient_user_id: log for log in rows}
        assert logs[subject].recipient_contact is None and logs[subject].event_payload is None
        assert logs[other].recipient_contact == "enc:keep@example.com"  # untouched


@pytest.mark.asyncio
async def test_erase_is_idempotent(client):
    company, subject = uuid.uuid4(), uuid.uuid4()
    await _seed(client._factory, company, subject, uuid.uuid4())

    first = await client.post(_URL, json={"user_id": str(subject)})
    assert first.json()["found"] is True
    second = await client.post(_URL, json={"user_id": str(subject)})
    assert second.status_code == 200
    assert second.json()["found"] is False, second.json()["rows_affected"]

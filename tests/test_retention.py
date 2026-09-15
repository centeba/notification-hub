"""Retention purge functions (SB-17).

Proves each bulk purge deletes only rows past its retention window and leaves
fresh rows untouched, against an in-memory SQLite session (same shape as the
other IH suites). Wide age margins (100+ days) keep the assertions insensitive
to any SQLite timezone quirk at the boundary.
"""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from integration_hub_backend.api.core.db import Base
from integration_hub_backend.api.models.delivery_log import NotificationDeliveryLog
from integration_hub_backend.api.models.device_token import DeviceToken
from integration_hub_backend.api.services.retention import (
    purge_ai_usage_events,
    purge_delivery_logs,
    purge_idle_device_tokens,
)

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


def _ago(days: int) -> datetime:
    return datetime.now(UTC) - timedelta(days=days)


@pytest.mark.asyncio
async def test_purge_delivery_logs_deletes_only_expired(db):
    company = uuid.uuid4()
    db.add_all(
        [
            NotificationDeliveryLog(
                id=uuid.uuid4(),
                company_id=company,
                event_type="ai_budget",
                channel="email",
                status="sent",
                created_at=_ago(120),  # expired (>90d)
            ),
            NotificationDeliveryLog(
                id=uuid.uuid4(),
                company_id=company,
                event_type="ai_budget",
                channel="email",
                status="sent",
                created_at=_ago(10),  # fresh
            ),
        ]
    )
    await db.commit()

    deleted = await purge_delivery_logs(db, older_than_days=90)
    await db.commit()

    assert deleted == 1
    remaining = (await db.execute(text("SELECT count(*) FROM notification_delivery_logs"))).scalar()
    assert remaining == 1


@pytest.mark.asyncio
async def test_purge_idle_device_tokens_deletes_only_idle(db):
    company, user = uuid.uuid4(), uuid.uuid4()
    db.add_all(
        [
            DeviceToken(
                id=uuid.uuid4(),
                user_id=user,
                company_id=company,
                platform="fcm",
                token="idle",
                created_at=_ago(400),
                updated_at=_ago(200),  # idle (>180d)
            ),
            DeviceToken(
                id=uuid.uuid4(),
                user_id=user,
                company_id=company,
                platform="fcm",
                token="active",
                created_at=_ago(400),
                updated_at=_ago(5),  # recently seen
            ),
        ]
    )
    await db.commit()

    deleted = await purge_idle_device_tokens(db, idle_days=180)
    await db.commit()

    assert deleted == 1
    kept = (await db.execute(text("SELECT token FROM device_tokens"))).scalars().all()
    assert kept == ["active"]


@pytest.mark.asyncio
async def test_purge_ai_usage_events_prunes_old(db):
    # ai_usage_events is created by migration in prod; here build a minimal table
    # for the raw-SQL purge to act on. Drop first: another test in the suite may
    # have registered the real model on Base (so create_all already made it), and
    # we want our known minimal schema regardless of test order.
    await db.execute(text("DROP TABLE IF EXISTS ai_usage_events"))
    await db.execute(
        text("CREATE TABLE ai_usage_events (id TEXT PRIMARY KEY, created_at TIMESTAMP NOT NULL)")
    )
    await db.execute(
        text("INSERT INTO ai_usage_events (id, created_at) VALUES (:i, :c)"),
        [
            {"i": str(uuid.uuid4()), "c": _ago(900)},  # old (>730d)
            {"i": str(uuid.uuid4()), "c": _ago(30)},  # recent
        ],
    )
    await db.commit()

    deleted = await purge_ai_usage_events(db, older_than_days=730)
    await db.commit()

    assert deleted == 1
    remaining = (await db.execute(text("SELECT count(*) FROM ai_usage_events"))).scalar()
    assert remaining == 1


@pytest.mark.asyncio
async def test_purges_are_noops_when_nothing_expired(db):
    company = uuid.uuid4()
    db.add(
        NotificationDeliveryLog(
            id=uuid.uuid4(),
            company_id=company,
            event_type="ai_budget",
            channel="email",
            status="sent",
            created_at=_ago(1),
        )
    )
    await db.commit()
    assert await purge_delivery_logs(db, older_than_days=90) == 0

"""Field-encryption-key rotation for integration-hub (SB-08).

Direct-key scheme (no DEK): rotation fully decrypts every FIELD_ENCRYPTION_KEY
column with the old key and re-encrypts with the new — across the three Text
columns and the three JSON ``{"encrypted": …}`` nests. Verified against a raw
SQLite schema with two random AES keys.
"""

import base64
import os
import uuid
from collections.abc import AsyncIterator
from typing import Any

import pytest
import pytest_asyncio
from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from sqlalchemy import JSON, Column, MetaData, Table, Text, Uuid, insert, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from integration_hub_backend.api.core.field_rotation import (
    rewrap_all_fields,
    rewrap_field,
)

pytestmark = pytest.mark.asyncio

_META = MetaData()
_CREDS = Table(
    "integration_credentials",
    _META,
    Column("id", Uuid, primary_key=True),
    Column("encrypted_data", Text),
)
_LOGS = Table(
    "notification_delivery_logs",
    _META,
    Column("id", Uuid, primary_key=True),
    Column("recipient_contact", Text),
)
_SYS = Table(
    "notification_system_integrations",
    _META,
    Column("id", Uuid, primary_key=True),
    Column("encrypted_config", Text),
)
_SETTINGS = Table(
    "notification_company_settings",
    _META,
    Column("id", Uuid, primary_key=True),
    Column("sms_provider_config", JSON),
)
_WEBHOOKS = Table(
    "notification_webhook_endpoints",
    _META,
    Column("id", Uuid, primary_key=True),
    Column("headers", JSON),
    Column("auth_config", JSON),
)


def _seal(plaintext: str, key: bytes) -> str:
    nonce = os.urandom(12)
    return base64.b64encode(nonce + AESGCM(key).encrypt(nonce, plaintext.encode(), None)).decode()


def _open(blob: str, key: bytes) -> str:
    raw = base64.b64decode(blob)
    return AESGCM(key).decrypt(raw[:12], raw[12:], None).decode()


@pytest_asyncio.fixture
async def sessions() -> AsyncIterator[async_sessionmaker[Any]]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(_META.create_all)
    yield async_sessionmaker(engine, expire_on_commit=False)
    await engine.dispose()


async def test_rewrap_field_round_trip() -> None:
    old, new = os.urandom(32), os.urandom(32)
    rotated = rewrap_field(_seal("s3cret", old), old_key=old, new_key=new)
    assert _open(rotated, new) == "s3cret"
    with pytest.raises(InvalidTag):
        _open(rotated, old)


async def test_rewrap_all_fields_rotates_both_shapes(
    sessions: async_sessionmaker[Any],
) -> None:
    old, new = os.urandom(32), os.urandom(32)
    ids = {name: uuid.uuid4() for name in ("cred", "log", "sys", "cfg", "hook")}
    async with sessions() as s:
        await s.execute(insert(_CREDS).values(id=ids["cred"], encrypted_data=_seal("cred", old)))
        await s.execute(
            insert(_LOGS).values(id=ids["log"], recipient_contact=_seal("+15551234567", old))
        )
        await s.execute(insert(_SYS).values(id=ids["sys"], encrypted_config=_seal("cfg", old)))
        # JSON nests — with an extra sibling key that must be preserved.
        await s.execute(
            insert(_SETTINGS).values(
                id=ids["cfg"],
                sms_provider_config={"encrypted": _seal("sms", old), "provider": "twilio"},
            )
        )
        await s.execute(
            insert(_WEBHOOKS).values(
                id=ids["hook"],
                headers={"encrypted": _seal("hdr", old)},
                auth_config={"encrypted": _seal("auth", old)},
            )
        )
        await s.commit()

    async with sessions() as s:
        counts = await rewrap_all_fields(s, old_key=old, new_key=new)
    assert counts == {
        "integration_credentials.encrypted_data": 1,
        "notification_delivery_logs.recipient_contact": 1,
        "notification_system_integrations.encrypted_config": 1,
        "notification_company_settings.sms_provider_config": 1,
        "notification_webhook_endpoints.headers": 1,
        "notification_webhook_endpoints.auth_config": 1,
    }

    async with sessions() as s:
        cred = (await s.execute(select(_CREDS))).mappings().one()
        assert _open(cred["encrypted_data"], new) == "cred"
        with pytest.raises(InvalidTag):
            _open(cred["encrypted_data"], old)

        settings_row = (await s.execute(select(_SETTINGS))).mappings().one()
        cfg = settings_row["sms_provider_config"]
        assert _open(cfg["encrypted"], new) == "sms"
        assert cfg["provider"] == "twilio"  # sibling key preserved

        hook = (await s.execute(select(_WEBHOOKS))).mappings().one()
        assert _open(hook["headers"]["encrypted"], new) == "hdr"
        assert _open(hook["auth_config"]["encrypted"], new) == "auth"

    # Resumable: a second sweep re-encrypts nothing (all already on the new key).
    async with sessions() as s:
        again = await rewrap_all_fields(s, old_key=old, new_key=new)
    assert sum(again.values()) == 0

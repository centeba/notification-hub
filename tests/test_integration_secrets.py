"""resolve_integration_secrets — per-company credential preferred over global.

The observability connector action routes (datadog/splunk/grafana/
elasticsearch/kibana) use this resolver so the Integration Hub "Connect"
UI actually drives them, while the global SystemIntegration stays as a
fallback.
"""

import uuid

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from integration_hub_backend.api.core.db import Base
from integration_hub_backend.api.crud.integration_credentials import create_credential
from integration_hub_backend.api.crud.system_integrations import update_system_integration
from integration_hub_backend.api.services.integration_secrets import (
    resolve_integration_secrets,
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


@pytest.mark.asyncio
async def test_returns_empty_when_nothing_configured(db):
    assert await resolve_integration_secrets(db, "datadog", uuid.uuid4()) == {}


@pytest.mark.asyncio
async def test_falls_back_to_global_when_no_company_credential(db):
    await update_system_integration(
        db,
        "elasticsearch",
        is_enabled=True,
        config={"url": "https://global-es:9200", "api_key": "global-key"},
    )
    secrets = await resolve_integration_secrets(db, "elasticsearch", uuid.uuid4())
    assert secrets["url"] == "https://global-es:9200"
    assert secrets["api_key"] == "global-key"


@pytest.mark.asyncio
async def test_disabled_global_is_ignored(db):
    await update_system_integration(
        db,
        "datadog",
        is_enabled=False,
        config={"api_key": "k"},
    )
    assert await resolve_integration_secrets(db, "datadog", uuid.uuid4()) == {}


@pytest.mark.asyncio
async def test_company_credential_preferred_and_base_url_normalized(db):
    company = uuid.uuid4()
    # Global says one thing…
    await update_system_integration(
        db,
        "elasticsearch",
        is_enabled=True,
        config={"url": "https://global-es:9200", "api_key": "global-key"},
    )
    # …but the tenant connected their own (Connect form stores base_url).
    await create_credential(
        db,
        company_id=company,
        name="My ES",
        type_="elasticsearch",
        secret_data={"base_url": "https://tenant-es:9200", "api_key": "tenant-key"},
        connector="elasticsearch",
    )
    secrets = await resolve_integration_secrets(db, "elasticsearch", company)
    # Per-company wins…
    assert secrets["api_key"] == "tenant-key"
    # …and base_url is aliased to url for the action code.
    assert secrets["url"] == "https://tenant-es:9200"


@pytest.mark.asyncio
async def test_company_isolation(db):
    org_a, org_b = uuid.uuid4(), uuid.uuid4()
    await create_credential(
        db,
        company_id=org_a,
        name="A datadog",
        type_="datadog",
        secret_data={"api_key": "a-key"},
        connector="datadog",
    )
    # org_b has no credential and no global → empty (doesn't see org_a's).
    assert await resolve_integration_secrets(db, "datadog", org_b) == {}
    assert (await resolve_integration_secrets(db, "datadog", org_a))["api_key"] == "a-key"


@pytest.mark.asyncio
async def test_no_company_id_uses_global_only(db):
    await update_system_integration(
        db,
        "splunk",
        is_enabled=True,
        config={"hec_token": "t", "hec_url": "https://splunk:8088"},
    )
    secrets = await resolve_integration_secrets(db, "splunk", None)
    assert secrets["hec_token"] == "t"

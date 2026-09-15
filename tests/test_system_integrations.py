import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from integration_hub_backend.api.core.db import Base
from integration_hub_backend.api.crud.system_integrations import (
    get_system_decrypted,
    get_system_integration,
    update_system_integration,
)

# Use SQLite for testing if possible, or a test PostgreSQL instance
DATABASE_URL = "sqlite+aiosqlite:///:memory:"


@pytest_asyncio.fixture
async def db_session():
    """Create a fresh in-memory database and return an async session."""
    engine = create_async_engine(DATABASE_URL)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    Session = async_sessionmaker(engine, expire_on_commit=False)
    async with Session() as session:
        yield session

    await engine.dispose()


@pytest.mark.asyncio
async def test_create_and_update_global_integration(db_session: AsyncSession):
    """Verify that system integrations can be created, updated, and correctly decrypted."""
    name = "splunk"
    config = {"hec_token": "splunk-token-123", "hec_url": "https://splunk:8088"}

    # 1. Create
    integration = await update_system_integration(db_session, name, is_enabled=True, config=config)
    assert integration.name == name
    assert integration.is_enabled is True

    # 2. Retrieve
    retrieved = await get_system_integration(db_session, name)
    assert retrieved is not None
    assert retrieved.is_enabled is True

    # 3. Decrypt
    decrypted = get_system_decrypted(retrieved)
    assert decrypted["hec_token"] == "splunk-token-123"
    assert decrypted["hec_url"] == "https://splunk:8088"

    # 4. Toggle Disable
    updated = await update_system_integration(db_session, name, is_enabled=False)
    assert updated.is_enabled is False

    # Ensure config persisted
    assert get_system_decrypted(updated)["hec_token"] == "splunk-token-123"


@pytest.mark.asyncio
async def test_update_non_existent_config(db_session: AsyncSession):
    """Verify that update works for integrations that don't yet exist in the DB."""
    name = "grafana"
    integration = await update_system_integration(db_session, name, is_enabled=True)
    assert integration.name == name
    assert integration.is_enabled is True
    assert get_system_decrypted(integration) == {}

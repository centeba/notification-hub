"""Alembic env.py — async SQLAlchemy migration runner."""

import asyncio
from logging.config import fileConfig

from alembic import context
from smart_llm.service_runtime import migration_db_url
from sqlalchemy import pool, text
from sqlalchemy.ext.asyncio import async_engine_from_config

# Import all models to populate Base.metadata
import integration_hub_backend.api.models  # noqa: F401
from integration_hub_backend.api.core.config import settings
from integration_hub_backend.api.core.db import Base

config = context.config
# RLS activation split (A2): run migrations as the privileged owner role when
# MIGRATION_DB_USER is set (so ALTER TABLE / CREATE POLICY succeed), while the
# app runtime connects as a non-superuser role so FORCE ROW LEVEL SECURITY bites.
# No-op when MIGRATION_DB_USER is unset.
config.set_main_option("sqlalchemy.url", migration_db_url(str(settings.SQLALCHEMY_DATABASE_URI)))

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        version_table="alembic_version",
        version_table_schema="notifications",
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection):
    # HA: serialize concurrent migrate-on-boot across co-booting replicas
    # (best-effort, lock_timeout-bounded — falls through to unserialized).
    from smart_llm.service_runtime import acquire_migration_lock

    acquire_migration_lock(connection)
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        version_table="alembic_version",
        version_table_schema="notifications",
    )
    with context.begin_transaction():
        context.run_migrations()


def _widen_alembic_version_pks(connection):
    """Pre-create alembic's bookkeeping table with VARCHAR(64)
    `version_num` BEFORE alembic auto-creates it at VARCHAR(32).

    Migration ``014_phase_g_grants_and_triggering`` is 33 chars, which
    truncates against the default VARCHAR(32) and aborts the migration
    transaction with ``StringDataRightTruncationError``. Pre-creating
    the table at 64 chars sidesteps this since alembic detects the
    existing table and reuses its schema.

    Runs on a SEPARATE committed transaction from the migration run
    (see ``run_async_migrations``) so the table persists even when
    migrations later roll back.

    Idempotent: CREATE IF NOT EXISTS on fresh, ALTER ... TYPE
    VARCHAR(64) is a no-op when the column is already wide.
    """
    connection.execute(text("CREATE SCHEMA IF NOT EXISTS notifications"))
    connection.execute(
        text(
            "CREATE TABLE IF NOT EXISTS notifications.alembic_version ("
            "  version_num VARCHAR(64) NOT NULL, "
            "  CONSTRAINT alembic_version_pkc PRIMARY KEY (version_num)"
            ")"
        )
    )
    connection.execute(
        text(
            "ALTER TABLE notifications.alembic_version   ALTER COLUMN version_num TYPE VARCHAR(64)"
        )
    )


async def run_async_migrations() -> None:
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    # Step 1: widen alembic_version on its own committed transaction so
    # the widening survives if migrations roll back.
    async with connectable.begin() as connection:
        await connection.run_sync(_widen_alembic_version_pks)

    # Step 2: run migrations normally.
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


def run_migrations_online() -> None:
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()

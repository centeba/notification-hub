"""Async SQLAlchemy database engine and session factory."""

import contextvars
import uuid
from collections.abc import AsyncGenerator

from smart_llm.service_runtime import resolve_pool_sizing
from sqlalchemy import Connection, event, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from integration_hub_backend.api.core.config import settings

# Single-replica budget; scaled down by REPLICA_COUNT so N replicas stay within
# Postgres max_connections (see smart_llm.service_runtime.resolve_pool_sizing).
_pool_size, _max_overflow = resolve_pool_sizing(20, 30)
engine = create_async_engine(
    settings.SQLALCHEMY_DATABASE_URI,
    pool_pre_ping=True,
    pool_size=_pool_size,
    max_overflow=_max_overflow,
    echo=settings.ENVIRONMENT == "local",
)

AsyncSessionLocal = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


# ── Tenant isolation via Postgres RLS (HARDENING-PLAN A2) ─────────────────────
#
# integration-hub is multi-tenant but also runs cross-tenant surfaces (platform
# admins, sibling-service M2M callers, an API-key bootstrap lookup), so it uses
# the same **two-GUC** model as user-master. The RLS migration
# (``029_rls_tenant_isolation``) scopes the tenant-private tables via two
# per-transaction GUCs, stamped by the engine ``begin`` listener from
# per-request/task contextvars (LOCAL → auto-clears, no pool leakage):
#
#   app.current_org  — the caller's company_id. NULL/'' → matches nothing.
#   app.bypass_rls   — 'on' for platform/system admins, internal-service callers,
#                      and the API-key bootstrap lookup (which reads
#                      ``notification_api_keys`` by prefix BEFORE the company is
#                      known). Those operate cross-tenant or before a tenant.
#
# Policy predicate: ``company_id = current_org() OR bypass``. An unstamped
# request (a route/worker that forgot to stamp) leaves both empty → zero rows
# (fail-closed), never a cross-tenant leak. ``get_current_user`` /
# ``require_any_auth`` stamp org (or bypass, for admins/internal) from the JWT;
# ``get_api_key_context`` bypasses for the prefix lookup then scopes to the
# resolved company; the Temporal dispatch/metrics/observability activities stamp
# their own ``company_id`` before touching a tenant table.
_current_org: contextvars.ContextVar[str] = contextvars.ContextVar("ih_current_org", default="")
_bypass_rls: contextvars.ContextVar[bool] = contextvars.ContextVar("ih_bypass_rls", default=False)


def set_current_org(org: uuid.UUID | str | None) -> None:
    """Scope the current request/task to ``org`` (clears any bypass)."""
    _bypass_rls.set(False)
    _current_org.set(str(org) if org else "")


def set_bypass_rls() -> None:
    """Mark the current request/task as RLS-exempt (platform admin, internal
    service, or a pre-tenant bootstrap lookup). Use only after the caller's
    privilege is established."""
    _bypass_rls.set(True)


def reset_tenant_context() -> None:
    """Reset to the fail-closed default (no org, no bypass → zero rows)."""
    _current_org.set("")
    _bypass_rls.set(False)


@event.listens_for(engine.sync_engine, "begin")
def _stamp_rls_guc(conn: Connection) -> None:
    # Postgres-only: set_config drives the RLS GUCs. Tests build the schema via
    # create_all (no policies) on sqlite, so this is a harmless no-op there.
    if conn.dialect.name != "postgresql":
        return
    conn.execute(
        text("SELECT set_config('app.current_org', :o, true)"),
        {"o": _current_org.get()},
    )
    conn.execute(
        text("SELECT set_config('app.bypass_rls', :b, true)"),
        {"b": "on" if _bypass_rls.get() else ""},
    )


class Base(DeclarativeBase):
    pass


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSessionLocal() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise

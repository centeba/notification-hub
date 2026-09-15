"""Postgres Row-Level Security tenant isolation for integration-hub (A2).

Proves the two-GUC policy migration 029 installs on the tenant-private tables
(``company_id = public.current_org() OR public.rls_bypass()``): a query with no
company predicate sees only the current tenant's rows; switching the org GUC
switches rows; ``bypass_rls='on'`` sees every tenant (platform admin / internal
service); an unset context sees ZERO rows (fail-closed); and WITH CHECK blocks
writing another tenant's row while bypass permits it.

RLS only applies on real Postgres and only a NON-superuser role feels FORCE RLS,
so this builds a throwaway schema + non-superuser role and drives it as that
role. Set ``RLS_TEST_DATABASE_URL`` to a superuser DSN to run.
"""

import os
import uuid

import pytest

DSN = os.environ.get("RLS_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not DSN, reason="RLS_TEST_DATABASE_URL not set")

_ORG = "public.current_org()"
_BYPASS = "public.rls_bypass()"
_PRED = f"(company_id = {_ORG} OR {_BYPASS})"


async def _setup(admin) -> tuple[uuid.UUID, uuid.UUID]:
    await admin.execute("DROP SCHEMA IF EXISTS rls_poc CASCADE")
    await admin.execute("DROP ROLE IF EXISTS rls_app")
    await admin.execute("CREATE SCHEMA rls_poc")
    # The two-GUC accessor functions (as migration 029 creates them).
    await admin.execute(
        "CREATE OR REPLACE FUNCTION public.current_org() RETURNS uuid "
        "LANGUAGE sql STABLE AS $$ "
        "SELECT NULLIF(current_setting('app.current_org', true), '')::uuid $$"
    )
    await admin.execute(
        "CREATE OR REPLACE FUNCTION public.rls_bypass() RETURNS boolean "
        "LANGUAGE sql STABLE AS $$ "
        "SELECT current_setting('app.bypass_rls', true) = 'on' $$"
    )
    # Shaped like ``integration_credentials``: an org-scoped secret store.
    await admin.execute(
        "CREATE TABLE rls_poc.integration_credentials ("
        "id uuid PRIMARY KEY DEFAULT gen_random_uuid(), "
        "company_id uuid NOT NULL, name text)"
    )
    await admin.execute("ALTER TABLE rls_poc.integration_credentials ENABLE ROW LEVEL SECURITY")
    await admin.execute("ALTER TABLE rls_poc.integration_credentials FORCE ROW LEVEL SECURITY")
    await admin.execute(
        f"CREATE POLICY tenant_isolation ON rls_poc.integration_credentials "
        f"USING ({_PRED}) WITH CHECK ({_PRED})"
    )
    await admin.execute("CREATE ROLE rls_app LOGIN PASSWORD 'apppw' NOSUPERUSER NOBYPASSRLS")
    await admin.execute("GRANT USAGE ON SCHEMA rls_poc TO rls_app")
    await admin.execute("GRANT EXECUTE ON FUNCTION public.current_org() TO rls_app")
    await admin.execute("GRANT EXECUTE ON FUNCTION public.rls_bypass() TO rls_app")
    await admin.execute(
        "GRANT SELECT, INSERT, UPDATE, DELETE ON rls_poc.integration_credentials TO rls_app"
    )
    org_a, org_b = uuid.uuid4(), uuid.uuid4()
    await admin.execute(
        "INSERT INTO rls_poc.integration_credentials (company_id, name) "
        "VALUES ($1,'a-1'),($1,'a-2'),($2,'b-1')",
        org_a,
        org_b,
    )
    return org_a, org_b


async def _teardown() -> None:
    import asyncpg

    admin = await asyncpg.connect(DSN)
    try:
        await admin.execute("DROP SCHEMA IF EXISTS rls_poc CASCADE")
        await admin.execute("DROP ROLE IF EXISTS rls_app")
        await admin.execute("DROP FUNCTION IF EXISTS public.rls_bypass()")
        await admin.execute("DROP FUNCTION IF EXISTS public.current_org()")
    finally:
        await admin.close()


async def test_two_guc_isolation_bypass_failclosed_and_with_check():
    import asyncpg

    admin = await asyncpg.connect(DSN)
    try:
        org_a, org_b = await _setup(admin)
    finally:
        await admin.close()

    app = await asyncpg.connect(dsn=DSN, user="rls_app", password="apppw")
    try:

        async def names():
            rows = await app.fetch("SELECT name FROM rls_poc.integration_credentials")
            return {r["name"] for r in rows}

        async def stamp(org: str = "", bypass: bool = False):
            await app.execute("SELECT set_config('app.current_org', $1, false)", org)
            await app.execute(
                "SELECT set_config('app.bypass_rls', $1, false)", "on" if bypass else ""
            )

        # Scoped to org A → only A's rows.
        await stamp(str(org_a))
        assert await names() == {"a-1", "a-2"}

        # Switch org → switch rows.
        await stamp(str(org_b))
        assert await names() == {"b-1"}

        # Bypass → every tenant (platform admin / internal service).
        await stamp(bypass=True)
        assert await names() == {"a-1", "a-2", "b-1"}

        # Unset context → zero rows (fail-closed).
        await stamp()
        assert await names() == set()

        # WITH CHECK: scoped to A cannot insert B's row...
        await stamp(str(org_a))
        with pytest.raises(asyncpg.exceptions.InsufficientPrivilegeError):
            await app.execute(
                "INSERT INTO rls_poc.integration_credentials (company_id, name) VALUES ($1,'evil')",
                org_b,
            )
        # ...but bypass may write any tenant's row.
        await stamp(bypass=True)
        await app.execute(
            "INSERT INTO rls_poc.integration_credentials (company_id, name) "
            "VALUES ($1,'admin-write')",
            org_b,
        )
    finally:
        await app.close()
        await _teardown()

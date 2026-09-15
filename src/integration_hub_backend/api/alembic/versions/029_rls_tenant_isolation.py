"""RLS tenant isolation for integration-hub tenant-private tables (HARDENING-PLAN A2)

integration-hub is multi-tenant but also runs cross-tenant surfaces (platform
admins, sibling-service M2M callers, an API-key bootstrap lookup), so this pass
uses the same **two-GUC** model as user-master rather than a single org stamp:

    app.current_org  — the caller's company_id (NULL/'' -> matches nothing)
    app.bypass_rls   — 'on' for platform/system admins, internal-service callers,
                       and the API-key bootstrap lookup (see core/db.py + deps.py)

Every policy is ``company_id = public.current_org() OR public.rls_bypass()``. An
unstamped request leaves both empty -> zero rows (fail-closed), never a
cross-tenant leak. The app stamps the GUCs from the JWT in ``get_current_user`` /
``require_any_auth`` (org, or bypass for admins/internal); ``get_api_key_context``
bypasses for the prefix lookup then scopes to the resolved company; the Temporal
dispatch/metrics/observability activities stamp their own company_id.

Scope — the clearly tenant-PRIVATE tables with clean stamp sites. Direct
``company_id`` tables scope on that column with scoped USING + scoped WITH CHECK.
``notification_delivery_logs`` is append-only and written from many origins (some
without a company stamp, e.g. the internal ai-usage alert insert), so it uses a
scoped USING but a permissive ``WITH CHECK (true)`` — isolate reads without
risking a write rejection (mirrors user-master's ``audit_log``).

Deliberately EXCLUDED this pass (each documented where it bites):
- ``notification_company_settings`` — read/written by the cross-service
  ``/ai-usage/assert-allowed`` endpoint (InternalServiceDep, company_id from the
  payload), whose stamping lives inside smart-llm's usage router, not here.
- ``notification_templates`` — the worker ``render_template_activity`` carries no
  company_id and must read both global and per-company templates; RLS would hide
  the company rows.
- ``notification_event_types`` — a global catalog (looked up by name with no
  company filter in ``evaluate_rules_activity``); NULL = system-global rows.
- ``inbound_connectors`` — all connector routes use ``require_internal_service``
  (no company stamp) and list/ingest cross-company by design.
- ``notification_channels`` / ``notification_system_integrations`` — global, no
  company column.
- the smart-llm-owned AI/usage/grant tables (``ai_skills``, ``ai_agent_configs``,
  ``ai_agent_skill_links``, ``agent_runs``, ``agent_action_audit``,
  ``ai_usage_events``, ``ai_agent_grants``, ``ai_skill_grants``, ``llm_api_keys``)
  — federated via ``grantee_company_id`` / ``acting_company_id`` /
  ``paying_company_id`` / ``triggering_company_id`` and shared with user-master's
  AI surface; they warrant a dedicated, coordinated RLS pass (owner: whichever
  service canonically writes them) rather than a naive company_id policy that
  would break cross-company grants and billing inserts.

Operator: the app must connect as a NON-superuser role without BYPASSRLS, or
FORCE RLS is bypassed and this migration is a no-op (dark). Migrations run as the
owner via ``migration_db_url`` (``MIGRATION_DB_USER``).

Revision ID: 029_rls_tenant_isolation
Revises: 028_pii_masking
Create Date: 2026-08-28
"""

from alembic import op

revision = "029_rls_tenant_isolation"
down_revision = "028_pii_masking"
branch_labels = None
depends_on = None

_ORG = "public.current_org()"
_BYPASS = "public.rls_bypass()"

# Direct company_id (NOT NULL) tenant-private tables — scoped USING + WITH CHECK.
_DIRECT = [
    "notification_webhook_endpoints",
    "notification_rules",
    "notification_preferences",
    "integration_credentials",
    "metric_facts",
    "device_tokens",
    "notification_api_keys",
]

# Append-only, mixed-origin: scoped reads, permissive writes.
_AUDIT = ["notification_delivery_logs"]


def upgrade() -> None:
    # GUC accessors. current_org(): empty -> NULL (-> no rows; fail-closed).
    op.execute(
        """
        CREATE OR REPLACE FUNCTION public.current_org() RETURNS uuid
        LANGUAGE sql STABLE AS $$
            SELECT NULLIF(current_setting('app.current_org', true), '')::uuid
        $$
        """
    )
    op.execute(
        """
        CREATE OR REPLACE FUNCTION public.rls_bypass() RETURNS boolean
        LANGUAGE sql STABLE AS $$
            SELECT current_setting('app.bypass_rls', true) = 'on'
        $$
        """
    )

    pred = f"(company_id = {_ORG} OR {_BYPASS})"
    for table in _DIRECT:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(f"CREATE POLICY tenant_isolation ON {table} USING ({pred}) WITH CHECK ({pred})")

    for table in _AUDIT:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(f"CREATE POLICY tenant_isolation ON {table} USING ({pred}) WITH CHECK (true)")


def downgrade() -> None:
    for table in [*_DIRECT, *_AUDIT]:
        op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {table}")
        op.execute(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY")
    op.execute("DROP FUNCTION IF EXISTS public.rls_bypass()")
    op.execute("DROP FUNCTION IF EXISTS public.current_org()")

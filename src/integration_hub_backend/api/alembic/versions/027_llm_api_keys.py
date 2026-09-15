"""Bring the shared ``llm_api_keys`` table under Alembic (pre-launch Gate 8)

``llm_api_keys`` (smart_llm.key_store.DatabaseKeyStore) is a SHARED table read at
runtime by six services (doc-vault, email-extractor, esignature, integration-hub,
mit-stack, user-master). Until now its DDL existed ONLY in
``key_store.create_tables()`` (a runtime ``Base.metadata.create_all``) and was
bootstrapped as a side-effect of *integration-hub* booting first — non-
deterministic, unordered vs. the services that read it, and invisible to Alembic.

This migration makes integration-hub the deterministic Alembic owner of the
table. It creates it from the model's OWN ``__table__`` with ``checkfirst=True``
so it (a) exactly matches ``smart_llm.models.LLMApiKey`` with zero hand-copied DDL
to drift, and (b) is idempotent — in already-deployed environments the table
already exists (from the old ``create_all``) and this is a no-op. The runtime
``create_tables()`` bootstrap is removed in the same change; the DDL is now
applied by migrate-on-boot, before the app serves traffic.

Revision ID: 027_llm_api_keys
Revises: 026_ai_usage_user_id
Create Date: 2026-08-06
"""

from __future__ import annotations

from alembic import op

revision = "027_llm_api_keys"
down_revision = "026_ai_usage_user_id"
branch_labels = None
depends_on = None


def _llm_api_keys_table():
    """The single source of truth for this table's DDL — the ORM model itself."""
    from smart_llm.models import LLMApiKey

    return LLMApiKey.__table__


def upgrade() -> None:
    # checkfirst=True → no-op where the old create_all() already made the table.
    _llm_api_keys_table().create(bind=op.get_bind(), checkfirst=True)


def downgrade() -> None:
    _llm_api_keys_table().drop(bind=op.get_bind(), checkfirst=True)

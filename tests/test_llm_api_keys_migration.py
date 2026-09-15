"""Gate 8: the shared ``llm_api_keys`` table is Alembic-owned and matches the model.

Migration ``027_llm_api_keys`` creates the table straight from
``smart_llm.models.LLMApiKey.__table__`` with ``checkfirst=True``. These tests
pin (a) the revision chain, (b) that the created table's columns exactly match
the model, and (c) idempotency — re-running the create on an existing table is a
no-op, not an error (the case in already-deployed environments where the old
runtime ``create_all()`` already made the table).
"""

from __future__ import annotations

import importlib.util
import pathlib

from sqlalchemy import create_engine, inspect

_MIGRATION = (
    pathlib.Path(__file__).resolve().parents[1]
    / "src/integration_hub_backend/api/alembic/versions/027_llm_api_keys.py"
)


def _load_migration():
    spec = importlib.util.spec_from_file_location("m027_llm_api_keys", _MIGRATION)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_revision_chain():
    m = _load_migration()
    assert m.revision == "027_llm_api_keys"
    assert m.down_revision == "026_ai_usage_user_id"


def test_creates_table_matching_model_idempotently():
    m = _load_migration()
    table = m._llm_api_keys_table()
    assert table.name == "llm_api_keys"

    engine = create_engine("sqlite://")
    # Mirrors the migration's upgrade(): create with checkfirst, twice.
    table.create(bind=engine, checkfirst=True)
    table.create(bind=engine, checkfirst=True)  # must be a silent no-op

    insp = inspect(engine)
    cols = {c["name"] for c in insp.get_columns("llm_api_keys")}
    assert cols == {
        "id",
        "provider",
        "encrypted_key",
        "is_active",
        "label",
        "scope_id",
        "created_at",
    }
    # The one-active-key-per-(scope,provider) guard index ships with the table.
    idx = {i["name"] for i in insp.get_indexes("llm_api_keys")}
    assert "ix_llm_api_keys_active_scope_provider" in idx


def test_downgrade_drops_table():
    m = _load_migration()
    table = m._llm_api_keys_table()
    engine = create_engine("sqlite://")
    table.create(bind=engine, checkfirst=True)
    assert inspect(engine).has_table("llm_api_keys")
    table.drop(bind=engine, checkfirst=True)
    assert not inspect(engine).has_table("llm_api_keys")

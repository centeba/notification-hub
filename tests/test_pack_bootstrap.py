"""R1 — pack discovery + install wiring on integration-hub startup.

These tests exercise :func:`bootstrap_packs` directly so we don't
need to spin a live FastAPI app. We mock ``discover_packs`` to
return a fixture manifest and assert the injected callbacks fire
once per contribution. The permission writer is replaced with a
stub recorder — we test the SQL shape it generates is covered by
the sb_core install_pack contract, not the live Postgres
round-trip (that's a chassis-level concern already covered by the
52 sb_core tests).
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from integration_hub_backend.api.services import pack_bootstrap


def _make_manifest():
    """Return a minimal PackManifest with 2 entities + 2 perms.
    Built lazily so the import lives inside the test (sb_core must
    be installed for these tests to run; if it isn't, pytest skips
    via the module-level guard below)."""
    from sb_core import NavEntry, PackManifest, SearchEntitySpec

    return PackManifest(
        name="test_pack",
        version="0.1.0",
        requires_core=">=0.1.0",
        nav_entries=(
            NavEntry(
                label_key="t.nav",
                icon="users",
                route="/t",
                color_hex="0xFF000000",
            ),
        ),
        search_entities={
            "t_alpha": SearchEntitySpec(
                table="alpha",
                schema="test_pack",
                scope_column="company_id",
                displayable=("id", "name"),
                label="Alpha",
            ),
            "t_beta": SearchEntitySpec(
                table="beta",
                schema="test_pack",
                scope_column="company_id",
                displayable=("id",),
                label="Beta",
            ),
        },
        permissions=("test_pack:read", "test_pack:write"),
    )


# Skip the whole module if sb_core isn't installed in the test env
# (early dev images may not have it; the production Dockerfile does).
pytest.importorskip("sb_core")


@pytest.mark.asyncio
async def test_bootstrap_packs_invokes_callbacks_per_contribution():
    """Each manifest's entities + permissions trigger one callback
    per item. Single-pack happy path."""
    manifest = _make_manifest()
    app = MagicMock()

    register_search_entity = MagicMock()
    # We stub the permission writer at its factory boundary so we
    # never touch a real DB session.
    permission_calls: list[tuple[str, str]] = []

    async def _stub_writer(slug: str, *, pack_name: str) -> None:
        permission_calls.append((slug, pack_name))

    with (
        patch.object(pack_bootstrap, "make_permission_writer", return_value=_stub_writer),
        patch("sb_core.discover_packs", return_value=[manifest]),
    ):
        summary = await pack_bootstrap.bootstrap_packs(
            app,
            session_factory=MagicMock(),  # unused — writer is stubbed
            register_search_entity=register_search_entity,
        )

    # Two entities → two register_search_entity calls.
    assert register_search_entity.call_count == 2
    names = sorted(c.args[0] for c in register_search_entity.call_args_list)
    assert names == ["t_alpha", "t_beta"]

    # Two permissions → two permission writer calls. pack_name
    # stamped correctly.
    assert sorted(permission_calls) == [
        ("test_pack:read", "test_pack"),
        ("test_pack:write", "test_pack"),
    ]

    assert summary == {
        "discovered": 1,
        "installed": 1,
        "failed": 0,
        "routers_mounted": True,
        "remote_contributions": 0,
    }


@pytest.mark.asyncio
async def test_bootstrap_packs_continues_after_single_failure():
    """One broken pack mustn't take down the host or block other
    packs from installing. The summary reports the failure count
    so operators see it in logs."""
    good = _make_manifest()
    # Build a second manifest with a different name; we force its
    # install to fail by raising on any entity whose key starts
    # with ``broken_``.
    from sb_core import PackManifest, SearchEntitySpec

    bad = PackManifest(
        name="broken_pack",
        version="0.1.0",
        requires_core=">=0.1.0",
        search_entities={
            "broken_x": SearchEntitySpec(
                table="x",
                schema="bad",
                scope_column="company_id",
                displayable=("id",),
                label="X",
            ),
        },
        permissions=("broken_pack:read",),
    )

    def _entity_recorder(name, spec):
        if name.startswith("broken_"):
            raise RuntimeError("boom")

    register_search_entity = MagicMock(side_effect=_entity_recorder)

    async def _stub_writer(slug: str, *, pack_name: str) -> None:
        pass

    with (
        patch.object(pack_bootstrap, "make_permission_writer", return_value=_stub_writer),
        patch("sb_core.discover_packs", return_value=[good, bad]),
    ):
        summary = await pack_bootstrap.bootstrap_packs(
            MagicMock(),
            session_factory=MagicMock(),
            register_search_entity=register_search_entity,
        )

    # The second pack's first entity raised; that pack's install
    # was aborted. The first pack still installed cleanly.
    assert summary["discovered"] == 2
    assert summary["installed"] + summary["failed"] == 2
    assert summary["failed"] >= 1


@pytest.mark.asyncio
async def test_bootstrap_packs_empty_entry_point_group_is_noop():
    """A host with no packs registered comes up cleanly with a
    zero-count summary. The common chassis-only deployment."""
    register_search_entity = MagicMock()

    with patch("sb_core.discover_packs", return_value=[]):
        summary = await pack_bootstrap.bootstrap_packs(
            MagicMock(),
            session_factory=MagicMock(),
            register_search_entity=register_search_entity,
        )

    assert summary == {
        "discovered": 0,
        "installed": 0,
        "failed": 0,
        "routers_mounted": True,
        "remote_contributions": 0,
    }
    register_search_entity.assert_not_called()


@pytest.mark.asyncio
async def test_bootstrap_packs_router_mount_failure_surfaces_in_summary():
    """If ``register_routers_for_all`` raises, the summary must
    record ``routers_mounted=False`` so operators reading the
    startup log can tell pack routes aren't live — without this
    the host looks healthy even though no pack endpoints answer."""
    manifest = _make_manifest()
    register_search_entity = MagicMock()

    async def _stub_writer(slug: str, *, pack_name: str) -> None:
        pass

    def _fail_mount(app, manifests):
        raise RuntimeError("mount blew up")

    with (
        patch.object(pack_bootstrap, "make_permission_writer", return_value=_stub_writer),
        patch("sb_core.discover_packs", return_value=[manifest]),
        patch("sb_core.register_routers_for_all", side_effect=_fail_mount),
    ):
        summary = await pack_bootstrap.bootstrap_packs(
            MagicMock(),
            session_factory=MagicMock(),
            register_search_entity=register_search_entity,
        )

    # install_pack itself still ran (entities + perms registered);
    # only the router mount blew up.
    assert summary["installed"] == 1
    assert summary["failed"] == 0
    assert summary["routers_mounted"] is False


def test_make_permission_writer_emits_idempotent_upsert():
    """The SQL emitted by the writer must include ``ON CONFLICT
    (slug) DO UPDATE`` so a redeploy doesn't blow up on existing
    rows, and must stamp ``pack_name`` from the bind so uninstall
    can find pack-owned rows."""
    captured: list[str] = []

    class _FakeSession:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def execute(self, stmt, params):
            captured.append(str(stmt))
            captured.append(repr(params))

        async def commit(self):
            pass

    def _factory():
        return _FakeSession()

    import asyncio

    writer = pack_bootstrap.make_permission_writer(_factory)
    asyncio.run(writer("test_pack:read", pack_name="test_pack"))

    sql, params = captured
    assert "ON CONFLICT (slug)" in sql
    assert "pack_name" in sql
    assert "test_pack:read" in params
    assert "test_pack" in params

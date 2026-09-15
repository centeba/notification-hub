"""Phase 1 (R1) — pack discovery + install glue for integration-hub.

Lives as its own module (rather than inline in ``api/main.py``) so
the discover-and-install loop is unit-testable without spinning the
whole FastAPI app. ``api/main.py`` calls :func:`bootstrap_packs` from
its ``@app.on_event("startup")`` hook.

Idempotency: every restart re-runs discover + install. The injected
permission shim writes ``INSERT … ON CONFLICT (slug) DO UPDATE SET
pack_name = EXCLUDED.pack_name``, which converts a chassis-owned row
(``pack_name IS NULL``) into pack-owned the first time a pack claims
the slug and is otherwise a no-op. Re-installing the same pack is
cheap; AI search entity registration is in-memory and overwrites
silently.
"""

import json
import os
from collections.abc import Callable
from typing import Any

import httpx
import structlog
from fastapi import FastAPI
from sqlalchemy import text as _sql_text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

log = structlog.get_logger(__name__)


def make_permission_writer(
    session_factory: async_sessionmaker[AsyncSession],
) -> Callable[..., Any]:
    """Build a ``register_permission(slug, *, pack_name)`` async
    callable that persists pack-owned RBAC permissions to the shared
    ``permission`` table. Idempotent via ``ON CONFLICT (slug)`` —
    re-running on every startup is harmless. The ``DO UPDATE`` branch
    rewrites ``pack_name`` only when it actually differs, so an
    existing chassis-owned row (``pack_name IS NULL``) is converted
    to pack-owned the first time a pack claims that slug, and stays
    stable thereafter."""

    async def _register_permission(slug: str, *, pack_name: str) -> None:
        async with session_factory() as s:
            await s.execute(
                _sql_text(
                    "INSERT INTO permission (id, slug, pack_name) "
                    "VALUES (gen_random_uuid(), :slug, :pack_name) "
                    "ON CONFLICT (slug) DO UPDATE "
                    "SET pack_name = EXCLUDED.pack_name "
                    "WHERE permission.pack_name IS DISTINCT FROM EXCLUDED.pack_name"
                ),
                {"slug": slug, "pack_name": pack_name},
            )
            await s.commit()

    return _register_permission


def make_role_template_writer(
    session_factory: async_sessionmaker[AsyncSession],
) -> Callable[..., Any]:
    """Build a ``register_role_template(*, pack_name, name, description,
    permission_slugs)`` async callable that persists a pack-contributed
    default role into the shared ``role_template`` catalog (owned by
    user-master, written here the same way ``make_permission_writer``
    writes the ``permission`` table).

    The catalog is pack-level, not per-company — user-master materialises
    a per-company ``Role`` from each template when a tenant is provisioned.
    Idempotent on ``(pack_name, name)``: re-running on every startup
    refreshes the description + permission set without creating duplicates,
    and never touches the per-company roles already materialised from it."""

    async def _register_role_template(
        *,
        pack_name: str,
        name: str,
        description: str = "",
        permission_slugs: list[str] | None = None,
    ) -> None:
        slugs_json = json.dumps(list(permission_slugs or []))
        async with session_factory() as s:
            await s.execute(
                _sql_text(
                    "INSERT INTO role_template "
                    "(id, pack_name, name, description, permission_slugs) "
                    "VALUES (gen_random_uuid(), :pack_name, :name, "
                    ":description, CAST(:slugs AS jsonb)) "
                    "ON CONFLICT (pack_name, name) DO UPDATE SET "
                    "description = EXCLUDED.description, "
                    "permission_slugs = EXCLUDED.permission_slugs"
                ),
                {
                    "pack_name": pack_name,
                    "name": name,
                    "description": description,
                    "slugs": slugs_json,
                },
            )
            await s.commit()

    return _register_role_template


def make_pack_node_type_writer() -> Callable[..., Any] | None:
    """Build a writer that POSTs each pack-contributed trigger / action
    / palette-group spec to Mit Stack's internal upsert endpoint.

    Returns ``None`` when ``MIT_STACK_URL`` or ``INTERNAL_API_KEY`` is
    not configured — pack manifests that declare workflow contributions
    will then log a warning via the chassis and skip silently, instead
    of blowing up host startup. This keeps deployments without Mit Stack
    (or with it on a different network segment) operable.

    The writer is async and fire-and-forget at the level of "one HTTP
    call per spec." Spec count is small (a typical pack contributes
    fewer than 20 entries), so the lack of batching is not a
    performance concern.
    """
    mit_stack_url = os.environ.get("MIT_STACK_URL", "").rstrip("/")
    internal_key = os.environ.get("INTERNAL_API_KEY") or os.environ.get("INTERNAL_SERVICE_SECRET")
    if not mit_stack_url or not internal_key:
        return None

    endpoint = f"{mit_stack_url}/api/v1/internal/node-types/upsert"

    async def _register(
        *,
        pack_name: str,
        kind: str,
        key: str,
        manifest_json: dict[str, Any],
    ) -> None:
        async with httpx.AsyncClient(timeout=10.0) as client:
            r = await client.post(
                endpoint,
                json={
                    "pack_name": pack_name,
                    "kind": kind,
                    "key": key,
                    "manifest_json": manifest_json,
                },
                headers={"X-Internal-Key": internal_key},
            )
            # Don't raise — pack bootstrap is best-effort. A bad
            # response means the entry won't show up in the palette,
            # which surfaces via the registry endpoint's healthcheck
            # rather than crashing host startup.
            if r.status_code >= 400:
                log.warning(
                    "pack_node_type_upsert_failed",
                    pack=pack_name,
                    kind=kind,
                    key=key,
                    status=r.status_code,
                    body=r.text[:300],
                )

    return _register


async def bootstrap_packs(
    app: FastAPI,
    *,
    session_factory: async_sessionmaker[AsyncSession],
    register_search_entity: Callable[..., None],
) -> dict[str, Any]:
    """Discover packs via the ``sb_pack`` entry-point group and
    install each into the running host.

    Returns a summary dict
    ``{discovered, installed, failed, routers_mounted}`` so the
    caller can log a single structured line. ``routers_mounted`` is
    ``False`` when ``register_routers_for_all`` raised — without
    this, a router-mount failure would look identical to a clean
    boot in the install log even though no pack HTTP routes are
    reachable.

    Each individual install failure is caught + logged so one
    broken pack doesn't take the whole host down.

    When the ``sb_core`` chassis is not installed (the standalone default),
    this is a no-op that returns a zeroed summary — notification-hub runs its
    own routes directly and needs no pack discovery."""
    try:
        import sb_core
        from sb_core import discover_packs, install_pack, register_routers_for_all
    except ImportError:
        log.info("sb_core_not_installed_packs_skipped")
        return {
            "discovered": 0,
            "installed": 0,
            "failed": 0,
            "routers_mounted": False,
            "remote_contributions": 0,
        }

    permission_writer = make_permission_writer(session_factory)
    role_template_writer = make_role_template_writer(session_factory)
    pack_node_type_writer = make_pack_node_type_writer()
    manifests = discover_packs()
    installed = 0
    failed = 0
    for m in manifests:
        try:
            await install_pack(
                m,
                register_search_entity=register_search_entity,
                register_permission=permission_writer,
                register_role_template=role_template_writer,
                chassis_version=sb_core.__version__,
                register_pack_node_type=pack_node_type_writer,
            )
            installed += 1
        except Exception as exc:  # noqa: BLE001
            failed += 1
            log.warning(
                "sb_pack_install_failed",
                pack=m.name,
                version=m.version,
                error=str(exc),
            )
    # Mount any pack-contributed routers under /api/{name}/v1/.
    # Hosts with no pack routers get a no-op pass.
    routers_mounted = True
    try:
        register_routers_for_all(app, manifests)
    except Exception as exc:  # noqa: BLE001
        routers_mounted = False
        log.warning("sb_pack_router_mount_failed", error=str(exc))

    # ── Remote packs ──────────────────────────────────────────────────
    # Discover packs that live in their own services (e.g. restoration-
    # api) and contribute via a published manifest at GET /pack/manifest.
    # Forwards just the workflow-builder contributions (triggers, actions,
    # palette groups, seed workflows) to Mit Stack — remote packs don't
    # share routers/permissions with this host.
    remote_installed = 0
    if pack_node_type_writer is not None:
        for url in _remote_pack_urls():
            try:
                count = await _forward_remote_manifest(url, pack_node_type_writer)
                remote_installed += count
                log.info(
                    "sb_pack_remote_installed",
                    url=url,
                    contributions=count,
                )
            except Exception as exc:  # noqa: BLE001
                log.warning(
                    "sb_pack_remote_install_failed",
                    url=url,
                    error=str(exc),
                )

    return {
        "discovered": len(manifests),
        "installed": installed,
        "failed": failed,
        "routers_mounted": routers_mounted,
        "remote_contributions": remote_installed,
    }


def _remote_pack_urls() -> list[str]:
    """Parse the ``REMOTE_PACK_URLS`` env var. Comma-separated list of
    base URLs whose ``/pack/manifest`` endpoint we should consume.
    Empty / missing = no remote packs."""
    raw = os.environ.get("REMOTE_PACK_URLS", "").strip()
    if not raw:
        return []
    return [u.strip().rstrip("/") for u in raw.split(",") if u.strip()]


async def _forward_remote_manifest(
    base_url: str,
    pack_node_type_writer: Callable[..., Any],
) -> int:
    """Fetch a remote pack manifest and forward its workflow-builder
    contributions to Mit Stack via the same writer used for local
    packs. Returns the number of contributions registered.

    Remote manifest schema mirrors :class:`sb_core.packs.manifest.PackManifest`
    serialised to JSON — see ``restoration/api/app/pack/manifest.py``
    for the canonical example.
    """
    url = f"{base_url}/pack/manifest"
    async with httpx.AsyncClient(timeout=10.0) as client:
        r = await client.get(url)
        r.raise_for_status()
        manifest = r.json()
    pack_name = str(manifest.get("name") or "")
    if not pack_name:
        raise ValueError(f"remote manifest at {url} has no `name`")

    count = 0
    for trig in manifest.get("workflow_triggers", []) or []:
        await pack_node_type_writer(
            pack_name=pack_name,
            kind="trigger",
            key=trig.get("key", ""),
            manifest_json=trig,
        )
        count += 1
    for act in manifest.get("workflow_actions", []) or []:
        await pack_node_type_writer(
            pack_name=pack_name,
            kind="action",
            key=act.get("key", ""),
            manifest_json=act,
        )
        count += 1
    for grp in manifest.get("palette_groups", []) or []:
        await pack_node_type_writer(
            pack_name=pack_name,
            kind="group",
            key=grp.get("key", ""),
            manifest_json=grp,
        )
        count += 1
    theme = manifest.get("theme")
    if isinstance(theme, dict) and theme:
        await pack_node_type_writer(
            pack_name=pack_name,
            kind="theme",
            # Use pack_name as the theme key — at most one theme
            # per pack, so this stays unique under
            # (pack_name, kind, key).
            key=pack_name,
            manifest_json=theme,
        )
        count += 1
    # Domain-data schema for the no-code condition builder. One row per
    # declared domain (keyed by domain.key under this pack_name).
    for dom in manifest.get("data_domains", []) or []:
        await pack_node_type_writer(
            pack_name=pack_name,
            kind="data_domain",
            key=dom.get("key", ""),
            manifest_json=dom,
        )
        count += 1
    # Authenticated-scraper templates (multi-tenant). One row per connector
    # (keyed by connector.key under this pack_name). Site knowledge only.
    for conn in manifest.get("scraper_connectors", []) or []:
        await pack_node_type_writer(
            pack_name=pack_name,
            kind="scraper_connector",
            key=conn.get("key", ""),
            manifest_json=conn,
        )
        count += 1
    return count

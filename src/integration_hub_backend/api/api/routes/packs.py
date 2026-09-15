"""Phase 1B — pack discovery + uninstall HTTP surface.

Two endpoints:

- ``GET /packs`` — lists every discovered :class:`PackManifest`.
  Read-only; any logged-in user can hit it (the frontend needs
  this to decide which optional UI surfaces to render). The
  response strips the ``router_factories`` field — they're
  callables and don't JSON-serialise.

- ``DELETE /packs/{name}`` — uninstall hook. ``PlatformAdminDep``
  gated. Runs :func:`sb_core.packs.uninstall_pack` with a
  host-supplied purge callable that deletes the pack's
  permissions and removes the pack name from every
  ``company.enabled_packs`` array.

The endpoints are deliberately thin — the chassis owns the
``uninstall_pack`` semantics; this router just translates HTTP
into the chassis call.
"""

from typing import Any

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import text

try:
    # ``sb_core`` is the SentinelBuild chassis pack framework. It is optional
    # for the standalone notification-hub: when absent, the pack endpoints
    # degrade to "no packs" rather than failing at import time.
    from sb_core import discover_packs, uninstall_pack

    _SB_CORE_AVAILABLE = True
except ImportError:  # pragma: no cover - exercised only without the chassis
    _SB_CORE_AVAILABLE = False

from integration_hub_backend.api.api.deps import (
    CurrentUser,
    PlatformAdminDep,
    SessionDep,
)

router = APIRouter(prefix="/packs", tags=["packs"])


class PackPublic(BaseModel):
    """JSON-safe view of a :class:`PackManifest`. Drops fields that
    don't serialise (callables, ``Path`` objects collapse to
    strings)."""

    name: str
    version: str
    requires_core: str
    nav_entries: list[dict[str, Any]]
    search_entities: list[str]
    permissions: list[str]
    seed_counts: dict[str, int]


@router.get("/", response_model=list[PackPublic])
async def list_packs(_user: CurrentUser) -> list[PackPublic]:
    """List every pack the chassis has discovered. Used by the
    frontend to render the Platform admin tab's pack toggles and
    to decide what shows up in per-tenant ``enabled_packs``
    pickers.

    Returns an empty list when the ``sb_core`` chassis is not installed
    (the standalone default) — there are no packs to discover."""
    if not _SB_CORE_AVAILABLE:
        return []
    manifests = discover_packs()
    return [
        PackPublic(
            name=m.name,
            version=m.version,
            requires_core=m.requires_core,
            nav_entries=[
                {
                    "label_key": n.label_key,
                    "icon": n.icon,
                    "route": n.route,
                    "color_hex": n.color_hex,
                    "group_key": n.group_key,
                }
                for n in m.nav_entries
            ],
            search_entities=list(m.search_entities.keys()),
            permissions=list(m.permissions),
            seed_counts={
                "agents": len(m.seed_agents),
                "skills": len(m.seed_skills),
                "workflows": len(m.seed_workflows),
                "rules": len(m.seed_rules),
                "forms": len(m.seed_forms),
            },
        )
        for m in manifests
    ]


@router.delete("/{pack_name}", status_code=204)
async def delete_pack(
    pack_name: str,
    session: SessionDep,
    _admin: PlatformAdminDep,
) -> None:
    """Uninstall a pack — wipes its perms + removes it from every
    tenant's ``enabled_packs``. Host restart required for in-memory
    contributions (nav entries, mounted routers, search registry)
    to clear; the response 204 reflects only the persistent
    cleanup."""
    if not _SB_CORE_AVAILABLE:
        raise HTTPException(
            status_code=status.HTTP_501_NOT_IMPLEMENTED,
            detail="pack management requires the sb_core chassis (not installed)",
        )

    async def _purge(name: str) -> None:
        # DELETE the pack's permissions first; any role_permission
        # rows cascade via FK.
        await session.execute(
            text("DELETE FROM permission WHERE pack_name = :p"),
            {"p": name},
        )
        # Pull the pack name from every tenant's enabled_packs array.
        # ``array_remove`` is a no-op when the name isn't present.
        await session.execute(
            text("UPDATE company SET enabled_packs = array_remove(enabled_packs, :p)"),
            {"p": name},
        )
        await session.commit()

    try:
        await uninstall_pack(pack_name, purge_persistent_state=_purge)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"uninstall failed: {e}",
        ) from e
    return None

"""Registry of entities exposed to natural-language search.

Each entry pins the table the LLM is allowed to write SQL against,
the column used for tenant scoping (varies — leads/contacts use
``company_id``; mit-stack tables use ``org_id``), and the columns
safe to return to the caller (strips internal/encrypted fields).

Adding a new entity is a one-line dict entry. The validator and the
endpoint pull the schema from here and from a live
``postgres_describe_table`` call so the LLM sees the actual column
types without hardcoded duplication.

Phase 1 (framework primitives): the registry is now **mutable**.
A pack registered via ``sb_core.packs.install_pack`` contributes
its entities through :func:`register_entity` at host startup; the
hardcoded ``_REGISTRY`` entries below are the chassis-owned
entities (leads, contacts, workflows, etc.) that ship with every
deployment.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class EntitySpec:
    table: str
    schema: str
    scope_column: str  # tenant column on the table
    displayable: tuple[str, ...]  # columns to return to caller (and to
    # describe to the LLM in the prompt)
    label: str  # human-friendly name for prompts
    default_order_by: str | None = None  # optional ORDER BY hint
    # Columns whose values are PII. Declared here (metadata) so the search
    # executor can pass those cell values into the smart-llm masking firewall as
    # exact hints on egress — masking still happens only in the firewall. Empty
    # tuple = rely on the firewall's detector alone.
    pii_columns: tuple[str, ...] = ()


_REGISTRY: dict[str, EntitySpec] = {
    # Phase 1A W3 — CRM tables physically moved to the ``pack_crm``
    # schema. The pack manifest in ``services/pack_crm/`` also
    # contributes these entries via :func:`register_entity`, so when
    # pack discovery runs at startup both registrations land on the
    # same shape (overwrite is silent + logged). Keeping the entries
    # hardcoded here ensures NL search keeps working even on a host
    # boot that hasn't yet discovered packs.
    "leads": EntitySpec(
        table="lead",
        schema="pack_crm",
        scope_column="company_id",
        displayable=(
            "id",
            "company_id",
            "contact_id",
            "title",
            "description",
            "stage",
            "value",
            "currency",
            "expected_close_date",
            "assigned_to",
            "created_by",
            "created_at",
            "updated_at",
        ),
        label="Lead",
        default_order_by="created_at DESC",
    ),
    "contacts": EntitySpec(
        table="contact",
        schema="pack_crm",
        scope_column="company_id",
        displayable=(
            "id",
            "company_id",
            "first_name",
            "last_name",
            "email",
            "phone",
            "job_title",
            "status",
            "source",
            "linked_company_name",
            "address_city",
            "address_state",
            "address_country",
            "created_at",
            "updated_at",
        ),
        label="Contact",
        default_order_by="created_at DESC",
        # Free-text PII a regex can't reliably catch (names) plus the
        # detector-covered ones, declared so exact values can be passed as
        # masking hints once the search executor consumes them.
        pii_columns=("first_name", "last_name", "email", "phone"),
    ),
    "workflows": EntitySpec(
        table="workflows",
        schema="public",
        scope_column="org_id",
        displayable=(
            "id",
            "org_id",
            "name",
            "description",
            "is_active",
            "trigger_type",
            "scope",
            "visibility",
            "created_by",
            "created_at",
            "updated_at",
        ),
        label="Workflow",
        default_order_by="updated_at DESC",
    ),
    "rules": EntitySpec(
        table="rules",
        schema="public",
        scope_column="org_id",
        displayable=(
            "id",
            "org_id",
            "name",
            "description",
            "is_active",
            "priority",
            "rule_type",
            "status",
            "category_id",
            "trigger_events",
            "created_at",
            "updated_at",
        ),
        label="Rule",
        default_order_by="priority ASC",
    ),
    "forms": EntitySpec(
        table="forms",
        schema="public",
        scope_column="org_id",
        displayable=(
            "id",
            "org_id",
            "name",
            "is_public",
            "slug",
            "scope",
            "visibility",
            "created_by",
            "created_at",
            "updated_at",
        ),
        label="Form",
        default_order_by="updated_at DESC",
    ),
    "tags": EntitySpec(
        table="curated_tags",
        schema="vault",
        scope_column="company_id",
        displayable=(
            "id",
            "name",
            "display_name",
            "scope",
            "company_id",
            "description",
            "color",
            "created_at",
        ),
        label="Tag",
        default_order_by="name ASC",
    ),
}


def get_entity(name: str) -> EntitySpec | None:
    return _REGISTRY.get(name)


def list_entities() -> list[str]:
    return sorted(_REGISTRY.keys())


def register_entity(name: str, spec: EntitySpec) -> None:
    """Pack-installed entity (Phase 1 framework primitives).

    Called by the host's pack installer for every entity contributed
    by a discovered :class:`sb_core.PackManifest`. Collisions log a
    warning and overwrite — packs declare their entities once at
    startup, so any collision is a developer bug (two packs picking
    the same name) that should be visible without silently failing.

    Accepts either the chassis-local :class:`EntitySpec` or anything
    duck-typed to it (e.g. ``sb_core.SearchEntitySpec``). When the
    incoming object isn't an ``EntitySpec`` we reconstruct one to
    preserve type-tag homogeneity in the registry.
    """
    if not isinstance(spec, EntitySpec):
        spec = EntitySpec(
            table=spec.table,
            schema=spec.schema,
            scope_column=spec.scope_column,
            displayable=tuple(spec.displayable),
            label=spec.label,
            default_order_by=getattr(spec, "default_order_by", None),
        )
    if name in _REGISTRY:
        logger.warning(
            "ai_search_registry: %r already registered — overwriting "
            "(check for duplicate pack contributions)",
            name,
        )
    _REGISTRY[name] = spec

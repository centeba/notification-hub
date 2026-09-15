"""Rule operations exposed as smart-llm ``ActionTool`` adapters.

The Rule Builder agent uses these to read existing notification
rules and create new ones from a natural-language description.
Mirrors the shape of ``postgres_service`` /
``email_service`` so the MCP dispatch table can wire to it
uniformly.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession


class RuleService:
    """Read + write notification rules without going through HTTP.

    All calls take ``company_id`` so the agent runtime is responsible
    for scoping. The ``Agent.run_with_skills`` caller passes it
    through the args model.
    """

    def __init__(self, db: AsyncSession):
        self.db = db

    @staticmethod
    def _rule_to_dict(r: Any) -> dict[str, Any]:
        return {
            "id": str(r.id),
            "name": r.name,
            "company_id": str(r.company_id),
            "event_type_id": str(r.event_type_id),
            "channel_ids": list(r.channel_ids or []),
            "template_id": str(r.template_id),
            "recipient_strategy": r.recipient_strategy,
            "recipient_config": r.recipient_config,
            "conditions": r.conditions,
            "priority": r.priority,
            "is_active": r.is_active,
            "created_at": r.created_at.isoformat() if r.created_at else None,
        }

    async def list_rules(
        self,
        company_id: uuid.UUID,
        active_only: bool = False,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        from integration_hub_backend.api.crud import rules as rules_crud

        items, _count = await rules_crud.list_rules(
            self.db,
            company_id,
            limit=limit,
            active_only=active_only,
        )
        return [self._rule_to_dict(r) for r in items]

    async def list_event_types(
        self,
        company_id: uuid.UUID,
    ) -> list[dict[str, Any]]:
        """List event types the agent can pick from when building a rule.

        Event types are the "trigger names" the platform emits
        (e.g. ``order.created``, ``invoice.failed``). They live in
        ``notification_event_types`` keyed by ``company_id`` so each
        tenant owns its own set.
        """
        from integration_hub_backend.api.models.event_type import NotificationEventType

        result = await self.db.execute(
            select(NotificationEventType).where(NotificationEventType.company_id == company_id)
        )
        return [
            {
                "id": str(et.id),
                "name": et.name,
                "description": getattr(et, "description", None),
            }
            for et in result.scalars().all()
        ]

    async def create_rule(
        self,
        company_id: uuid.UUID,
        created_by: uuid.UUID,
        name: str,
        event_type_id: uuid.UUID,
        channel_ids: list[uuid.UUID],
        template_id: uuid.UUID,
        recipient_strategy: str = "all_users",
        recipient_config: dict[str, Any] | None = None,
        conditions: list[dict[str, Any]] | None = None,
        priority: int = 5,
    ) -> dict[str, Any]:
        """Create a notification rule. Wraps ``crud.rules.create_rule``
        so the smart-llm dispatch helper hits a uniform shape."""
        from integration_hub_backend.api.crud import rules as rules_crud
        from integration_hub_backend.api.models.rule import RuleCreate

        # Build a RuleCreate that the existing CRUD accepts. The
        # ``conditions`` field is a list[Condition]; we accept a list
        # of plain dicts here and let RuleCreate's pydantic validation
        # reshape them.
        payload = RuleCreate(
            name=name,
            event_type_id=event_type_id,
            channel_ids=channel_ids,
            template_id=template_id,
            recipient_strategy=recipient_strategy,
            recipient_config=recipient_config,
            conditions=conditions,
            priority=priority,
        )
        rule = await rules_crud.create_rule(
            self.db,
            company_id=company_id,
            created_by=created_by,
            data=payload,
        )
        return self._rule_to_dict(rule)

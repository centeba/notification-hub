"""Audit logging helper — records significant actions for compliance and debugging."""

from __future__ import annotations

import uuid
from typing import Any

import structlog

log = structlog.get_logger(__name__)


async def log_audit(
    session: Any,
    *,
    user_id: uuid.UUID,
    company_id: uuid.UUID,
    action: str,
    target_type: str,
    target_id: str,
    details: dict[str, Any] | None = None,
) -> None:
    """Log an audit event.

    Currently writes to the structured logger. A future iteration can persist
    these to an ``audit_logs`` database table by inserting an ORM row here
    and flushing (the calling router commits the session).
    """
    log.info(
        "audit_event",
        user_id=str(user_id),
        company_id=str(company_id),
        action=action,
        target_type=target_type,
        target_id=target_id,
        details=details or {},
    )

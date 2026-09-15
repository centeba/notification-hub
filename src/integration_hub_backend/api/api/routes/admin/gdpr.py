"""Internal route — GDPR right-to-erasure for a data subject (SB-17).

Called by the cross-service erasure orchestrator (see docs/gdpr-erasure.md).
integration-hub holds the subject's *own* notification data, so erasure here:

- **deletes** the subject's device push tokens (``device_tokens``) and their
  per-user notification preferences (``notification_preferences``) — these carry
  no audit value once the subject is gone;
- **anonymizes in place** the delivery-log audit rows addressed to the subject:
  the (already AES-256-GCM-encrypted) ``recipient_contact`` and the
  ``event_payload`` are NULLed while the row is kept as a delivery record.

Idempotent (a re-run affects 0 rows). RLS-exempt — erasure spans tenants by
design — so the handler stamps :func:`set_bypass_rls`.

Auth: ``X-Internal-Key`` (or legacy ``Authorization: Bearer ${INTERNAL_SERVICE_SECRET}``)
via :data:`InternalServiceDep`. Not reachable through the external nginx ingress.
"""

import uuid
from datetime import UTC, datetime
from typing import Any, cast

from fastapi import APIRouter
from pydantic import BaseModel
from sqlalchemy import CursorResult, null, or_
from sqlalchemy import delete as sa_delete
from sqlalchemy import update as sa_update

from integration_hub_backend.api.api.deps import InternalServiceDep, SessionDep
from integration_hub_backend.api.core.db import set_bypass_rls
from integration_hub_backend.api.models.delivery_log import NotificationDeliveryLog
from integration_hub_backend.api.models.device_token import DeviceToken
from integration_hub_backend.api.models.preference import NotificationPreference

router = APIRouter(prefix="/internal", tags=["internal"])


class EraseSubjectRequest(BaseModel):
    user_id: uuid.UUID
    # Accepted for cross-service contract uniformity; integration-hub keys the
    # subject by user_id and bypasses RLS, so neither field is required here.
    company_id: uuid.UUID | None = None
    email: str | None = None


@router.post("/gdpr/erase-subject")
async def erase_subject(
    body: EraseSubjectRequest,
    session: SessionDep,
    _internal: InternalServiceDep,
) -> dict[str, Any]:
    """Erase the subject's notification PII across integration-hub (SB-17)."""
    set_bypass_rls()  # cross-tenant erase (RLS-exempt by design)
    uid = body.user_id
    counts: dict[str, int] = {}

    res = cast(
        "CursorResult[Any]",
        await session.execute(sa_delete(DeviceToken).where(DeviceToken.user_id == uid)),
    )
    counts["device_tokens_deleted"] = res.rowcount or 0

    res = cast(
        "CursorResult[Any]",
        await session.execute(
            sa_delete(NotificationPreference).where(NotificationPreference.user_id == uid)
        ),
    )
    counts["notification_preferences_deleted"] = res.rowcount or 0

    # Delivery logs are audit records → anonymize in place (keep the row, scrub
    # PII). Keyed on recipient_user_id (which is preserved), so guard on the
    # scrubbed columns still being set — otherwise a re-run keeps "matching"
    # already-anonymized rows and the call never reports idempotent (found=0).
    res = cast(
        "CursorResult[Any]",
        await session.execute(
            sa_update(NotificationDeliveryLog)
            .where(
                NotificationDeliveryLog.recipient_user_id == uid,
                or_(
                    NotificationDeliveryLog.recipient_contact.isnot(None),
                    NotificationDeliveryLog.event_payload.isnot(None),
                ),
            )
            # ``null()`` writes a true SQL NULL — assigning Python ``None`` to a
            # JSON(B) column stores the JSON value 'null' (not SQL NULL), which
            # would keep matching the isnot(None) guard and defeat idempotency.
            .values(recipient_contact=null(), event_payload=null())
        ),
    )
    counts["delivery_logs_anonymized"] = res.rowcount or 0

    await session.commit()
    return {
        "service": "integration-hub",
        "found": sum(counts.values()) > 0,
        "rows_affected": counts,
        "erased_at": datetime.now(UTC).isoformat(),
    }

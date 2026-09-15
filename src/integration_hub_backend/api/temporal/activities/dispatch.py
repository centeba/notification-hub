"""Temporal activities for the NotificationDispatchWorkflow."""

import uuid
from dataclasses import dataclass
from datetime import datetime, time
from typing import Any

import httpx
import structlog
from jinja2 import Environment, StrictUndefined, TemplateError, UndefinedError
from smart_llm.resilience import CircuitOpenError, resilient_section
from temporalio import activity

from integration_hub_backend.api.core.config import settings
from integration_hub_backend.api.core.rules_engine import evaluate_conditions
from integration_hub_backend.api.models.delivery_log import DeliveryStatus
from integration_hub_backend.api.models.rule import RecipientStrategy
from integration_hub_backend.api.models.template import SUPPORTED_LANGUAGES

log = structlog.get_logger(__name__)

# ── Input / Result dataclasses ────────────────────────────────────────────────


@dataclass
class EventInput:
    event_id: str
    event_type: str
    company_id: str
    payload: dict[str, Any]


@dataclass
class RecipientInfo:
    user_id: str
    email: str | None
    phone: str | None
    language: str
    company_id: str


@dataclass
class RenderedTemplate:
    channel: str
    subject: str | None
    body_text: str
    body_html: str | None
    webhook_payload: dict[str, Any] | None


@dataclass
class DeliveryResult:
    channel: str
    recipient_user_id: str
    status: str
    provider_message_id: str | None = None
    error: str | None = None


# ── Activities ────────────────────────────────────────────────────────────────


@activity.defn
async def evaluate_rules_activity(event: EventInput) -> list[dict[str, Any]]:
    """Fetch matching active rules for this event type + company."""
    from sqlalchemy import select

    from integration_hub_backend.api.core.db import AsyncSessionLocal, set_current_org
    from integration_hub_backend.api.crud.rules import get_active_rules_for_event
    from integration_hub_backend.api.models.event_type import NotificationEventType

    # Worker path → stamp the RLS tenant GUC (reads notification_rules).
    set_current_org(event.company_id)
    async with AsyncSessionLocal() as db:
        # Find event type by name
        result = await db.execute(
            select(NotificationEventType).where(
                NotificationEventType.name == event.event_type,
                NotificationEventType.is_active == True,  # noqa: E712
            )
        )
        event_type = result.scalar_one_or_none()
        if not event_type:
            log.warning("event_type_not_found", event_type=event.event_type)
            return []

        rules = await get_active_rules_for_event(
            db,
            company_id=uuid.UUID(event.company_id),
            event_type_id=event_type.id,
        )

        matching = []
        for rule in rules:
            conditions = rule.conditions
            if evaluate_conditions(conditions, event.payload):
                matching.append(
                    {
                        "rule_id": str(rule.id),
                        "channel_ids": rule.channel_ids,
                        "recipient_strategy": rule.recipient_strategy,
                        "recipient_config": rule.recipient_config,
                        "template_id": str(rule.template_id),
                        "priority": rule.priority,
                    }
                )

        log.info("rules_evaluated", event_type=event.event_type, matched=len(matching))
        return matching


@activity.defn
async def fetch_recipients_activity(
    rule: dict[str, Any], company_id: str, payload: dict[str, Any]
) -> list[dict[str, Any]]:
    """Fetch recipient contact info from User Master, filtered by preferences/quiet hours."""
    from integration_hub_backend.api.core.db import AsyncSessionLocal
    from integration_hub_backend.api.core.redis import get_redis_pool
    from integration_hub_backend.api.crud.company_settings import get_company_settings
    from integration_hub_backend.api.integrations.user_master_client import UserMasterClient

    redis = get_redis_pool()
    client = UserMasterClient(redis)
    cid = uuid.UUID(company_id)

    strategy = rule["recipient_strategy"]
    config = rule.get("recipient_config") or {}

    if strategy == RecipientStrategy.ALL_USERS:
        contacts = await client.get_company_users(cid)
    elif strategy == RecipientStrategy.ROLE:
        role = config.get("role", "user")
        contacts = await client.get_users_by_role(cid, role)
    elif strategy == RecipientStrategy.SPECIFIC:
        user_ids = config.get("user_ids", [])
        contacts = []
        for uid in user_ids:
            c = await client.get_user_contact(uuid.UUID(uid))
            if c:
                contacts.append(c)
    elif strategy == RecipientStrategy.EVENT_FIELD:
        field_path = config.get("field", "user_id")
        # Get value from payload using dot notation
        from integration_hub_backend.api.core.rules_engine import _get_nested

        user_id_val = _get_nested(payload, field_path)
        contacts = []
        if user_id_val:
            c = await client.get_user_contact(uuid.UUID(str(user_id_val)))
            if c:
                contacts.append(c)
    else:
        contacts = []

    # Resolve default language from company settings
    async with AsyncSessionLocal() as db:
        company_settings = await get_company_settings(db, cid)
        default_lang = company_settings.default_language if company_settings else "en"

    result = []
    for contact in contacts:
        lang = contact.language or default_lang
        if lang not in SUPPORTED_LANGUAGES:
            lang = "en"
        result.append(
            {
                "user_id": str(contact.user_id),
                "email": contact.email,
                "phone": contact.phone,
                "language": lang,
                "company_id": str(contact.company_id) if contact.company_id else company_id,
            }
        )

    return result


@activity.defn
async def resolve_channel_activity(channel_id: str) -> str | None:
    """Resolve a channel UUID → its name (email/sms/webhook/push). Closes the
    placeholder in NotificationDispatchWorkflow so channel branches actually
    fire. Returns None for unknown/inactive channels (caller skips)."""
    from sqlalchemy import select

    from integration_hub_backend.api.core.db import AsyncSessionLocal
    from integration_hub_backend.api.models.channel import NotificationChannel

    try:
        cid = uuid.UUID(str(channel_id))
    except (ValueError, TypeError):
        return None
    async with AsyncSessionLocal() as db:
        row = (
            await db.execute(
                select(NotificationChannel.name, NotificationChannel.is_active).where(
                    NotificationChannel.id == cid
                )
            )
        ).first()
    if not row or not row.is_active:
        return None
    resolved_name: str = row.name
    return resolved_name


def _in_quiet_hours(now_t: time, start: time | None, end: time | None) -> bool:
    if start is None or end is None:
        return False
    if start <= end:
        return start <= now_t <= end
    # Overnight window (e.g. 22:00–07:00).
    return now_t >= start or now_t <= end


@activity.defn
async def check_recipient_preference_activity(
    user_id: str | None, company_id: str, channel_id: str
) -> bool:
    """A8 — enforce per-user channel preferences: a recipient who muted this
    channel (is_enabled=False), or is currently inside their quiet hours, is
    skipped. No preference row → allowed (opt-out model). Fail-open on error so
    a pref-lookup glitch never silently drops all notifications."""
    if not user_id:
        return True
    from zoneinfo import ZoneInfo

    from sqlalchemy import select

    from integration_hub_backend.api.core.db import AsyncSessionLocal, set_current_org
    from integration_hub_backend.api.models.preference import NotificationPreference

    try:
        uid = uuid.UUID(str(user_id))
        cid = uuid.UUID(str(company_id))
        chid = uuid.UUID(str(channel_id))
    except (ValueError, TypeError):
        return True
    # Worker path → stamp the RLS tenant GUC (reads notification_preferences).
    set_current_org(cid)
    try:
        async with AsyncSessionLocal() as db:
            pref = (
                await db.execute(
                    select(NotificationPreference).where(
                        NotificationPreference.user_id == uid,
                        NotificationPreference.company_id == cid,
                        NotificationPreference.channel_id == chid,
                    )
                )
            ).scalar_one_or_none()
        if pref is None:
            return True
        if not pref.is_enabled:
            return False
        if pref.quiet_hours_start and pref.quiet_hours_end:
            try:
                tz = ZoneInfo(pref.timezone or "UTC")
            except Exception:  # noqa: BLE001
                tz = ZoneInfo("UTC")
            now_t = datetime.now(tz).time()
            if _in_quiet_hours(now_t, pref.quiet_hours_start, pref.quiet_hours_end):
                return False
        return True
    except Exception as exc:  # noqa: BLE001
        log.warning("preference_check_failed", user_id=user_id, error=str(exc))
        return True


@activity.defn
async def render_template_activity(
    template_id: str,
    language: str,
    payload: dict[str, Any],
    channel_name: str,
) -> dict[str, Any] | None:
    """Render a Jinja2 template for a given channel and language."""
    from integration_hub_backend.api.core.db import AsyncSessionLocal
    from integration_hub_backend.api.crud.templates import get_template_for_language

    async with AsyncSessionLocal() as db:
        template = await get_template_for_language(db, uuid.UUID(template_id), language)
        if not template:
            log.warning("template_not_found", template_id=template_id, language=language)
            return None

        env = Environment(autoescape=True, undefined=StrictUndefined)

        # Each render failure is appended here as
        # {field, error_type, message}. The workflow inspects this list
        # to decide whether to branch (notify owner, skip channel, fall
        # back to a default template) instead of either crashing the
        # workflow (the previous Strict behavior) or silently shipping
        # `{{ missing_var }}` literal text to a recipient.
        errors: list[dict[str, str]] = []

        def safe_render(field: str, source: str | None) -> str | None:
            if not source:
                return None
            try:
                return env.from_string(source).render(**payload)
            except UndefinedError as e:
                log.warning(
                    "template_render_undefined",
                    template_id=template_id,
                    field=field,
                    error=str(e),
                )
                errors.append({"field": field, "error_type": "undefined", "message": str(e)})
                return None
            except TemplateError as e:
                # Syntax error, recursion, filter failure, etc.
                log.warning(
                    "template_render_error",
                    template_id=template_id,
                    field=field,
                    error=str(e),
                )
                errors.append({"field": field, "error_type": "template", "message": str(e)})
                return None

        rendered: dict[str, Any] = {
            "channel": channel_name,
            "subject": safe_render("subject", template.subject),
            "body_text": safe_render("body_text", template.body_text) or "",
            "body_html": safe_render("body_html", template.body_html),
            "webhook_payload": template.webhook_payload_template,
        }
        if errors:
            rendered["render_errors"] = errors
        return rendered


# Delivery activities split errors into two buckets:
#
# - **Transient** (network error, 5xx from the side-service) → re-raise
#   so Temporal's retry policy kicks in. The workflow eventually fails
#   the delivery row to FAILED if all retries are exhausted, but the
#   transient-error window gets a real retry chance instead of being
#   silently absorbed.
# - **Permanent** (4xx, bad recipient address, missing config) →
#   return ``{status: FAILED, ...}``. Temporal marks the activity
#   succeeded; the workflow writes the failed delivery row and moves
#   on. Retrying would never help.
#
# The previous version absorbed every exception as a permanent
# failure, which meant a complete outage of the email-service produced
# zero Temporal alarms and zero retries.


def _is_transient_http_error(exc: Exception) -> bool:
    """Classify exception as a retryable transport-layer failure."""
    if isinstance(exc, (httpx.TimeoutException, httpx.NetworkError, httpx.RemoteProtocolError)):
        return True
    if isinstance(exc, httpx.HTTPStatusError):
        return 500 <= exc.response.status_code < 600
    return False


@activity.defn
async def send_email_activity(
    recipient: dict[str, Any],
    rendered: dict[str, Any],
    from_address: str,
    from_name: str,
) -> dict[str, Any]:
    """Send email via the email-service microservice.

    Wrapped in a circuit breaker keyed by ``email-service`` so a
    side-service outage doesn't burn every Temporal retry on every
    queued notification — the breaker opens and the activity returns
    FAILED with a typed reason until the cool-down window passes.
    """
    try:
        async with resilient_section("email-service", failure_threshold=10, recovery_timeout=30.0):
            async with httpx.AsyncClient(timeout=30.0) as client:
                try:
                    response = await client.post(
                        f"{settings.EMAIL_SERVICE_URL}/send",
                        json={
                            "to": recipient["email"],
                            "subject": rendered.get("subject", "Notification"),
                            "body_html": rendered.get("body_html"),
                            "body_text": rendered.get("body_text", ""),
                            "from_address": from_address,
                            "from_name": from_name,
                        },
                        headers={"Authorization": f"Bearer {settings.INTERNAL_SERVICE_SECRET}"},
                    )
                    response.raise_for_status()
                    data = response.json()
                    return {
                        "status": DeliveryStatus.SENT,
                        "provider_message_id": data.get("message_id"),
                    }
                except Exception as e:
                    log.error("send_email_failed", error=str(e), recipient=recipient.get("email"))
                    if _is_transient_http_error(e):
                        # Re-raise — counts as a breaker failure and
                        # Temporal retries the activity.
                        raise
                    # Permanent failure (bad address, 4xx). Don't trip
                    # the breaker on the host's behalf.
                    return {"status": DeliveryStatus.FAILED, "error": str(e)}
    except CircuitOpenError as e:
        log.warning("send_email_circuit_open", retry_after_s=e.retry_after)
        return {
            "status": DeliveryStatus.FAILED,
            "error": "email-service unavailable (circuit open)",
        }


@activity.defn
async def send_sms_activity(
    recipient: dict[str, Any],
    rendered: dict[str, Any],
    company_id: str,
) -> dict[str, Any]:
    """Send SMS via the sms-service microservice."""
    if not recipient.get("phone"):
        return {"status": DeliveryStatus.FAILED, "error": "No phone number for recipient"}

    from integration_hub_backend.api.core.db import AsyncSessionLocal
    from integration_hub_backend.api.crud.company_settings import (
        get_company_settings,
        get_sms_provider_config,
    )

    async with AsyncSessionLocal() as db:
        cs = await get_company_settings(db, uuid.UUID(company_id))
        sms_provider = cs.sms_provider if cs else "twilio"
        provider_config = get_sms_provider_config(cs) if cs else {}

    # Per-provider breaker so a Twilio outage doesn't trip the AWS-SNS
    # path and vice versa.
    breaker_name = f"sms-{sms_provider}"
    try:
        async with resilient_section(breaker_name, failure_threshold=5, recovery_timeout=30.0):
            async with httpx.AsyncClient(timeout=30.0) as client:
                try:
                    response = await client.post(
                        f"{settings.SMS_SERVICE_URL}/send",
                        json={
                            "to": recipient["phone"],
                            "body": rendered.get("body_text", ""),
                            "provider": sms_provider,
                            "provider_config": provider_config,
                        },
                        headers={"Authorization": f"Bearer {settings.INTERNAL_SERVICE_SECRET}"},
                    )
                    response.raise_for_status()
                    data = response.json()
                    return {
                        "status": DeliveryStatus.SENT,
                        "provider_message_id": data.get("message_id"),
                    }
                except Exception as e:
                    log.error(
                        "send_sms_failed",
                        provider=sms_provider,
                        error=str(e),
                        recipient=recipient.get("phone"),
                    )
                    if _is_transient_http_error(e):
                        raise
                    return {"status": DeliveryStatus.FAILED, "error": str(e)}
    except CircuitOpenError as e:
        log.warning("send_sms_circuit_open", provider=sms_provider, retry_after_s=e.retry_after)
        return {
            "status": DeliveryStatus.FAILED,
            "error": f"sms provider {sms_provider!r} unavailable (circuit open)",
        }


@activity.defn
async def send_push_activity(
    recipient: dict[str, Any], rendered: dict[str, Any], company_id: str
) -> dict[str, Any]:
    """A8 — deliver a push notification to the recipient's active device tokens
    via the configured provider (PUSH_PROVIDER_URL). No provider / no tokens →
    a clean 'failed' result (logged), never raises (best-effort channel)."""
    import os

    from sqlalchemy import select

    from integration_hub_backend.api.core.db import AsyncSessionLocal, set_current_org
    from integration_hub_backend.api.models.device_token import DeviceToken

    user_id = recipient.get("user_id")
    if not user_id:
        return {"status": "failed", "error": "no user_id"}
    try:
        uid = uuid.UUID(str(user_id))
    except (ValueError, TypeError):
        return {"status": "failed", "error": "bad user_id"}

    # Worker path → stamp the RLS tenant GUC (device_tokens is filtered by
    # user_id only; the RLS policy adds the company_id predicate).
    set_current_org(company_id)
    async with AsyncSessionLocal() as db:
        tokens = (
            await db.execute(
                select(DeviceToken.platform, DeviceToken.token).where(
                    DeviceToken.user_id == uid,
                    DeviceToken.is_active.is_(True),
                )
            )
        ).all()
    if not tokens:
        return {"status": "failed", "error": "no registered devices"}

    provider_url = os.environ.get("PUSH_PROVIDER_URL")
    if not provider_url:
        log.info("push_no_provider", user_id=str(user_id), devices=len(tokens))
        return {"status": "failed", "error": "no push provider configured"}

    body = {
        "tokens": [{"platform": p, "token": t} for p, t in tokens],
        "title": rendered.get("subject") or "Notification",
        "body": rendered.get("body_text") or "",
        "data": rendered.get("data") or {},
    }
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(provider_url, json=body)
        if resp.status_code < 300:
            return {"status": "sent", "provider_message_id": None}
        return {"status": "failed", "error": f"provider {resp.status_code}"}
    except Exception as exc:  # noqa: BLE001
        log.warning("push_send_failed", error=str(exc))
        return {"status": "failed", "error": str(exc)}


@activity.defn
async def call_webhook_activity(
    endpoint_id: str,
    rendered: dict[str, Any],
    payload: dict[str, Any],
) -> dict[str, Any]:
    """Call an outbound webhook via the webhook-service microservice."""
    from sqlalchemy import select

    from integration_hub_backend.api.core.db import AsyncSessionLocal
    from integration_hub_backend.api.models.webhook_endpoint import NotificationWebhookEndpoint

    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(NotificationWebhookEndpoint).where(
                NotificationWebhookEndpoint.id == uuid.UUID(endpoint_id),
                NotificationWebhookEndpoint.is_active == True,  # noqa: E712
            )
        )
        endpoint = result.scalar_one_or_none()
        if not endpoint:
            return {"status": DeliveryStatus.FAILED, "error": "Webhook endpoint not found"}

    # Per-endpoint-host breaker so one user's broken webhook URL
    # doesn't tarpit calls to every other webhook routed through the
    # same side-service. We name the breaker after the destination
    # host, not the side-service, because the side-service itself is
    # rarely the bottleneck — the receiving endpoint is.
    try:
        from urllib.parse import urlparse

        host = urlparse(endpoint.url).hostname or "unknown"
    except Exception:
        host = "unknown"
    breaker_name = f"webhook-{host}"

    try:
        async with resilient_section(breaker_name, failure_threshold=10, recovery_timeout=60.0):
            async with httpx.AsyncClient(timeout=30.0) as client:
                try:
                    response = await client.post(
                        f"{settings.WEBHOOK_SERVICE_URL}/send",
                        json={
                            "url": endpoint.url,
                            "method": endpoint.http_method,
                            "payload": rendered.get("webhook_payload") or payload,
                            "auth_type": endpoint.auth_type,
                            "timeout_seconds": endpoint.timeout_seconds,
                        },
                        headers={"Authorization": f"Bearer {settings.INTERNAL_SERVICE_SECRET}"},
                    )
                    response.raise_for_status()
                    return {"status": DeliveryStatus.SENT}
                except Exception as e:
                    log.error(
                        "call_webhook_failed", endpoint_id=endpoint_id, host=host, error=str(e)
                    )
                    # Re-raise so the breaker records the failure;
                    # the surrounding try-CircuitOpenError catches the
                    # exhausted path.
                    raise
    except CircuitOpenError as e:
        log.warning("call_webhook_circuit_open", host=host, retry_after_s=e.retry_after)
        return {
            "status": DeliveryStatus.FAILED,
            "error": f"webhook host {host!r} unavailable (circuit open)",
        }
    except Exception as e:
        # Final fallback — breaker recorded the failure, we still
        # return FAILED so the workflow can move on.
        return {"status": DeliveryStatus.FAILED, "error": str(e)}


@activity.defn
async def log_delivery_activity(
    rule_id: str | None,
    event_type: str,
    event_payload: dict[str, Any],
    channel: str,
    recipient_user_id: str | None,
    recipient_contact: str | None,
    status: str,
    provider_message_id: str | None = None,
    error_message: str | None = None,
) -> str:
    """Write an immutable delivery log record to the database."""
    from integration_hub_backend.api.core.db import AsyncSessionLocal
    from integration_hub_backend.api.crud.delivery_logs import (
        create_delivery_log,
        update_delivery_status,
    )

    async with AsyncSessionLocal() as db:
        log_entry = await create_delivery_log(
            db=db,
            rule_id=uuid.UUID(rule_id) if rule_id else None,
            event_type=event_type,
            event_payload=event_payload,
            channel=channel,
            recipient_user_id=uuid.UUID(recipient_user_id) if recipient_user_id else None,
            recipient_contact=recipient_contact,
        )
        await update_delivery_status(
            db=db,
            log_id=log_entry.id,
            status=DeliveryStatus(status),
            provider_message_id=provider_message_id,
            error_message=error_message,
        )
        return str(log_entry.id)

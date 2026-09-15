"""Email send endpoint."""

import uuid
from typing import Any

import emails
import structlog
from fastapi import APIRouter, Depends, HTTPException, Security, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, EmailStr

from integration_hub_backend.email.core.config import settings

log = structlog.get_logger(__name__)
router = APIRouter()

bearer = HTTPBearer()


def verify_internal_token(
    credentials: HTTPAuthorizationCredentials = Security(bearer),
) -> None:
    # SEC-M2 — fail CLOSED on an unset secret and compare in constant time.
    # (The "changethis" default must be overridden in production — see the
    # service .env.example; not special-cased here so local dev still works.)
    import hmac

    secret = settings.INTERNAL_SERVICE_SECRET or ""
    if not secret:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="internal service secret not configured",
        )
    if not hmac.compare_digest(credentials.credentials, secret):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid service token"
        )


class SendEmailRequest(BaseModel):
    to: EmailStr
    subject: str
    body_text: str
    body_html: str | None = None
    from_address: str = ""
    from_name: str = ""


class SendEmailResponse(BaseModel):
    message_id: str
    status: str


@router.post("/send", response_model=SendEmailResponse)
async def send_email(
    body: SendEmailRequest,
    _: None = Depends(verify_internal_token),
) -> SendEmailResponse:
    from_addr = body.from_address or settings.DEFAULT_FROM_ADDRESS
    from_name = body.from_name or settings.DEFAULT_FROM_NAME

    message = emails.Message(
        subject=body.subject,
        text=body.body_text,
        html=body.body_html,
        mail_from=(from_name, from_addr),
    )

    smtp_kwargs: dict[str, Any] = {
        "host": settings.SMTP_HOST,
        "port": settings.SMTP_PORT,
    }
    if settings.SMTP_USER:
        smtp_kwargs["user"] = settings.SMTP_USER
        smtp_kwargs["password"] = settings.SMTP_PASSWORD
    if settings.SMTP_TLS:
        smtp_kwargs["tls"] = True

    try:
        response = message.send(to=body.to, smtp=smtp_kwargs)
        if response.status_code not in (250, 200):
            raise Exception(f"SMTP error: {response.status_code} {response.error}")
    except Exception as e:
        log.error("email_send_failed", to=body.to, error=str(e))
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Failed to send email: {e}",
        )

    message_id = str(uuid.uuid4())
    log.info("email_sent", to=body.to, subject=body.subject, message_id=message_id)
    return SendEmailResponse(message_id=message_id, status="sent")

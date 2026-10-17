"""SMS send endpoint."""

from typing import Any

import structlog
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from smart_llm.internal_auth import require_internal_key

from integration_hub_backend.sms.providers import get_provider

log = structlog.get_logger(__name__)
router = APIRouter()


class SendSMSRequest(BaseModel):
    to: str
    body: str
    provider: str = "twilio"  # "twilio" | "aws_sns"
    provider_config: dict[str, Any] = {}
    from_number: str | None = None


class SendSMSResponse(BaseModel):
    message_id: str
    status: str


@router.post("/send", response_model=SendSMSResponse)
async def send_sms(
    body: SendSMSRequest,
    _: None = Depends(require_internal_key),
) -> SendSMSResponse:
    if not body.to:
        raise HTTPException(status_code=400, detail="Recipient phone number required")
    if not body.body:
        raise HTTPException(status_code=400, detail="SMS body cannot be empty")

    try:
        provider = get_provider(body.provider, body.provider_config)
        result = await provider.send(to=body.to, body=body.body, from_number=body.from_number)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        log.error("sms_send_error", to=body.to, error=str(e))
        raise HTTPException(status_code=502, detail=f"SMS delivery failed: {e}")

    if result.status == "failed":
        raise HTTPException(status_code=502, detail=result.error or "SMS delivery failed")

    return SendSMSResponse(message_id=result.message_id, status=result.status)

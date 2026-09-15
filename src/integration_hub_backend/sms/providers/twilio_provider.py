"""Twilio SMS provider."""

from __future__ import annotations

import asyncio

import structlog
from twilio.base.exceptions import TwilioRestException
from twilio.rest import Client as TwilioClient

from integration_hub_backend.sms.providers.base import SMSProvider, SMSResult

log = structlog.get_logger(__name__)


class TwilioProvider(SMSProvider):
    def __init__(self, account_sid: str, auth_token: str, from_number: str) -> None:
        self._client = TwilioClient(account_sid, auth_token)
        self._from_number = from_number

    async def send(
        self,
        to: str,
        body: str,
        from_number: str | None = None,
    ) -> SMSResult:
        sender = from_number or self._from_number
        try:
            # Twilio SDK is sync — run in thread pool to avoid blocking
            message = await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: self._client.messages.create(
                    body=body,
                    from_=sender,
                    to=to,
                ),
            )
            log.info("twilio_sms_sent", to=to, sid=message.sid)
            return SMSResult(message_id=message.sid, status="sent")
        except TwilioRestException as e:
            log.error("twilio_sms_failed", to=to, error=str(e))
            return SMSResult(message_id="", status="failed", error=str(e))

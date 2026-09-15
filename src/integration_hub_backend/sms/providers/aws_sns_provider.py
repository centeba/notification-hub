"""AWS SNS SMS provider."""

from __future__ import annotations

import structlog
from aiobotocore.session import get_session

from integration_hub_backend.sms.providers.base import SMSProvider, SMSResult

log = structlog.get_logger(__name__)


class AWSSNSProvider(SMSProvider):
    def __init__(
        self,
        access_key_id: str,
        secret_access_key: str,
        region: str = "us-east-1",
        sender_id: str = "NotifHub",
    ) -> None:
        self._access_key_id = access_key_id
        self._secret_access_key = secret_access_key
        self._region = region
        self._sender_id = sender_id

    async def send(
        self,
        to: str,
        body: str,
        from_number: str | None = None,
    ) -> SMSResult:
        session = get_session()
        try:
            async with session.create_client(
                "sns",
                region_name=self._region,
                aws_access_key_id=self._access_key_id,
                aws_secret_access_key=self._secret_access_key,
            ) as client:
                response = await client.publish(
                    PhoneNumber=to,
                    Message=body,
                    MessageAttributes={
                        "AWS.SNS.SMS.SenderID": {
                            "DataType": "String",
                            "StringValue": self._sender_id,
                        },
                        "AWS.SNS.SMS.SMSType": {
                            "DataType": "String",
                            "StringValue": "Transactional",
                        },
                    },
                )
                message_id = response.get("MessageId", "")
                log.info("aws_sns_sms_sent", to=to, message_id=message_id)
                return SMSResult(message_id=message_id, status="sent")
        except Exception as e:
            log.error("aws_sns_sms_failed", to=to, error=str(e))
            return SMSResult(message_id="", status="failed", error=str(e))

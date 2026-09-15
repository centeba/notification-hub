"""Abstract SMS provider interface."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class SMSResult:
    message_id: str
    status: str
    error: str | None = None


class SMSProvider(ABC):
    @abstractmethod
    async def send(
        self,
        to: str,
        body: str,
        from_number: str | None = None,
    ) -> SMSResult: ...

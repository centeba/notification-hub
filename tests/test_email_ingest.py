"""Email ingest reads the mailbox through the hub's EmailService in-process,
scoped to the schedule's org."""

import uuid
from contextlib import asynccontextmanager
from typing import Any

import pytest

from integration_hub_backend.api.core import db as hub_db
from integration_hub_backend.api.services import email_service
from integration_hub_backend.email import ingest

ORG = uuid.uuid4()
CRED = uuid.uuid4()


class _FakeService:
    calls: list[tuple[str, dict[str, Any]]] = []

    def __init__(self, db: object) -> None:
        pass

    async def gmail_list_unread(self, **kw: Any) -> dict[str, Any]:
        self.calls.append(("gmail", kw))
        return {
            "messages": [
                {"id": "g1", "subject": "Hi", "from": "a@x.com", "date": "d", "body_plain": "body"}
            ]
        }

    async def outlook_list_messages(self, **kw: Any) -> dict[str, Any]:
        self.calls.append(("outlook", kw))
        return {
            "messages": [
                {"id": "o1", "subject": "Yo", "from": "b@x.com", "date": "d", "preview": "p"}
            ]
        }


@pytest.fixture(autouse=True)
def _in_process(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    _FakeService.calls = []
    stamped: list[str] = []

    @asynccontextmanager
    async def _session():  # type: ignore[no-untyped-def]
        yield object()

    monkeypatch.setattr(email_service, "EmailService", _FakeService)
    monkeypatch.setattr(hub_db, "AsyncSessionLocal", _session)
    monkeypatch.setattr(hub_db, "set_current_org", lambda org: stamped.append(str(org)))
    return stamped


def _params(provider: str, subject_filter: str = "") -> ingest._FetchEmailsParams:
    return ingest._FetchEmailsParams(
        org_id=str(ORG),
        credential_id=str(CRED),
        provider=provider,
        folder="Inbox",
        subject_filter=subject_filter,
        max_results=5,
    )


async def test_gmail_reads_in_process_for_the_org(_in_process: list[str]) -> None:
    emails = await ingest.fetch_emails_via_hub(_params("gmail"))

    assert _in_process == [str(ORG)]
    assert _FakeService.calls == [
        (
            "gmail",
            {"company_id": ORG, "credential_id": CRED, "query": "is:unread", "max_results": 5},
        )
    ]
    assert emails == [
        {"message_id": "g1", "subject": "Hi", "sender": "a@x.com", "body": "body", "date": "d"}
    ]


async def test_outlook_filters_by_subject_and_falls_back_to_the_preview() -> None:
    emails = await ingest.fetch_emails_via_hub(_params("outlook", subject_filter="Invoice"))

    provider, kw = _FakeService.calls[0]
    assert provider == "outlook"
    assert kw["filter_query"] == "isRead eq false and contains(subject, 'Invoice')"
    assert emails[0]["body"] == "p"


async def test_unknown_provider_is_rejected_before_any_read() -> None:
    with pytest.raises(ValueError, match="Unsupported provider"):
        await ingest.fetch_emails_via_hub(_params("imap"))
    assert _FakeService.calls == []

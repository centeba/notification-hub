import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
import respx

from integration_hub_backend.api.services.ai_service import AIService
from integration_hub_backend.api.services.email_service import EmailService

# Mock data
MOCK_COMPANY_ID = uuid.uuid4()
MOCK_CREDENTIAL_ID = uuid.uuid4()
MOCK_TOKEN = "fake-access-token-12345"


@pytest.fixture
def mock_db():
    db = AsyncMock()
    # ``AIService.complete`` calls ``_load_monthly_budget`` which does
    # ``(await db.execute(stmt)).scalars().first()``. Give ``execute`` a
    # synchronous result object so that chain works (no budget row → None →
    # unlimited). Tests needing real rows override ``db.execute``.
    result = MagicMock()
    result.scalars.return_value.first.return_value = None
    result.scalars.return_value.all.return_value = []
    result.scalar_one_or_none.return_value = None
    db.execute = AsyncMock(return_value=result)
    return db


@pytest.fixture
def mock_get_credential():
    with patch(
        "integration_hub_backend.api.services.email_service.get_credential", new_callable=AsyncMock
    ) as mock_get:
        # We also need to mock get_decrypted or make the credential object respond accordingly
        mock_get.return_value = {"id": MOCK_CREDENTIAL_ID}
        yield mock_get


@pytest.fixture
def mock_get_decrypted():
    with patch("integration_hub_backend.api.services.email_service.get_decrypted") as mock_decrypt:
        mock_decrypt.return_value = {"access_token": MOCK_TOKEN}
        yield mock_decrypt


@pytest.mark.asyncio
@respx.mock
async def test_gmail_send_success(mock_db, mock_get_credential, mock_get_decrypted):
    """Verify Gmail send functionality correctly prepares the request."""
    # Mock the Gmail API
    respx.post("https://gmail.googleapis.com/gmail/v1/users/me/messages/send").mock(
        return_value=httpx.Response(200, json={"id": "msg123", "threadId": "thr123"})
    )

    service = EmailService(mock_db)

    result = await service.gmail_send(
        company_id=MOCK_COMPANY_ID,
        credential_id=MOCK_CREDENTIAL_ID,
        to="test@example.com",
        subject="Test Subject",
        body="Hello World",
    )

    assert result["id"] == "msg123"
    assert result["threadId"] == "thr123"
    mock_get_credential.assert_called_once_with(mock_db, MOCK_CREDENTIAL_ID, MOCK_COMPANY_ID)
    mock_get_decrypted.assert_called_once()


@pytest.mark.asyncio
@respx.mock
async def test_outlook_send_success(mock_db, mock_get_credential, mock_get_decrypted):
    """Verify Outlook send functionality translates payload correctly for Microsoft Graph."""
    # Mock Graph API
    respx.post("https://graph.microsoft.com/v1.0/me/sendMail").mock(
        return_value=httpx.Response(202, json={})  # Outlook often returns 202 Accepted
    )

    service = EmailService(mock_db)

    result = await service.outlook_send(
        company_id=MOCK_COMPANY_ID,
        credential_id=MOCK_CREDENTIAL_ID,
        to=["user1@test.com", "user2@test.com"],
        subject="Graph Test",
        body_html="<p>HTML Body</p>",
    )

    assert result["status"] == "sent"
    assert result["subject"] == "Graph Test"
    mock_get_credential.assert_called_once_with(mock_db, MOCK_CREDENTIAL_ID, MOCK_COMPANY_ID)


@pytest.mark.asyncio
async def test_email_service_missing_credential(mock_db, mock_get_credential):
    """Ensure an error is raised if the credential cannot be found."""
    mock_get_credential.return_value = None

    service = EmailService(mock_db)

    with pytest.raises(ValueError, match="Credential not found"):
        await service.gmail_send(
            company_id=MOCK_COMPANY_ID,
            credential_id=MOCK_CREDENTIAL_ID,
            to="test@example.com",
            subject="Test Subject",
            body="Hello World",
        )


@pytest.mark.asyncio
async def test_claude_complete_success(mock_db):
    """Verify AIService routes completions through the smart-llm Agent.

    Primary key resolution uses the smart-llm key store; this test mocks
    get_company_api_key to return a key directly.
    """
    from smart_llm.base import LLMResponse

    mock_response = LLMResponse(
        data={"answer": "42"},
        provider="anthropic",
        metadata={
            "agent_name": f"integration-hub-{MOCK_COMPANY_ID}",
            "model": "claude-3-5-sonnet-20240620",
        },
    )

    with (
        patch(
            "integration_hub_backend.api.services.ai_service.get_company_api_key",
            new_callable=AsyncMock,
        ) as mock_key,
        patch("integration_hub_backend.api.services.ai_service.Agent") as MockAgent,
    ):
        mock_key.return_value = "sk-ant-test-key"

        mock_agent_instance = AsyncMock()
        mock_agent_instance.analyze = AsyncMock(return_value=mock_response)
        MockAgent.return_value = mock_agent_instance

        service = AIService(mock_db)
        result = await service.complete(
            company_id=MOCK_COMPANY_ID,
            prompt="What is the meaning of life?",
        )

    assert result["data"] == {"answer": "42"}
    assert result["provider"] == "anthropic"
    assert result["model"] == "claude-3-5-sonnet-20240620"

    # Verify Agent was constructed with the right core args. The service also
    # passes budget/usage kwargs (usage_session, usage_model, company_id,
    # monthly_budget_usd); assert the subset that this test cares about so the
    # check stays robust to those additions.
    MockAgent.assert_called_once()
    _, kwargs = MockAgent.call_args
    assert kwargs["name"] == f"integration-hub-{MOCK_COMPANY_ID}"
    assert kwargs["provider_type"] == "anthropic"
    assert kwargs["system_prompt"] == "You are a helpful assistant. Respond in JSON."
    assert kwargs["api_key"] == "sk-ant-test-key"
    assert kwargs["model_name"] == "claude-3-5-sonnet-20240620"
    mock_agent_instance.analyze.assert_called_once_with(
        input_text="What is the meaning of life?",
        context=None,
    )


@pytest.mark.asyncio
async def test_claude_complete_no_key_raises(mock_db):
    """Verify AIService raises when neither the key store nor the credential
    store can supply an API key."""
    with patch(
        "integration_hub_backend.api.services.ai_service.get_company_api_key",
        new_callable=AsyncMock,
    ) as mock_key:
        mock_key.return_value = None  # Key store empty

        service = AIService(mock_db)
        with pytest.raises(ValueError, match="No LLM API key found"):
            await service.complete(
                company_id=MOCK_COMPANY_ID,
                prompt="Who am I?",
                # No credential_id — no fallback available
            )


@pytest.mark.asyncio
async def test_claude_complete_openai_provider(mock_db):
    """Verify AIService passes the correct provider_type to the Agent when
    a non-anthropic provider is requested."""
    from smart_llm.base import LLMResponse

    mock_response = LLMResponse(
        data={"answer": "gpt says hi"},
        provider="openai",
        metadata={"model": "gpt-4o"},
    )

    with (
        patch(
            "integration_hub_backend.api.services.ai_service.get_company_api_key",
            new_callable=AsyncMock,
        ) as mock_key,
        patch("integration_hub_backend.api.services.ai_service.Agent") as MockAgent,
    ):
        mock_key.return_value = "sk-openai-test"

        mock_agent_instance = AsyncMock()
        mock_agent_instance.analyze = AsyncMock(return_value=mock_response)
        MockAgent.return_value = mock_agent_instance

        service = AIService(mock_db)
        result = await service.complete(
            company_id=MOCK_COMPANY_ID,
            prompt="Hello from OpenAI",
            provider="openai",
            model_name="gpt-4o",
        )

    assert result["provider"] == "openai"
    assert result["model"] == "gpt-4o"
    MockAgent.assert_called_once()
    _, kwargs = MockAgent.call_args
    assert kwargs["name"] == f"integration-hub-{MOCK_COMPANY_ID}"
    assert kwargs["provider_type"] == "openai"
    assert kwargs["system_prompt"] == "You are a helpful assistant. Respond in JSON."
    assert kwargs["api_key"] == "sk-openai-test"
    assert kwargs["model_name"] == "gpt-4o"
    # Key store must have been queried with "openai", not "anthropic"
    mock_key.assert_called_once_with(mock_db, MOCK_COMPANY_ID, "openai")


@pytest.mark.asyncio
async def test_claude_complete_legacy_credential_fallback(mock_db):
    """Verify AIService falls back to the integration_credentials store when the
    smart-llm key store has no key for this company."""
    from smart_llm.base import LLMResponse

    mock_response = LLMResponse(
        data={"result": "ok"},
        provider="anthropic",
        metadata={"model": "claude-3-5-sonnet-20240620"},
    )

    with (
        patch(
            "integration_hub_backend.api.services.ai_service.get_company_api_key",
            new_callable=AsyncMock,
        ) as mock_key,
        patch(
            "integration_hub_backend.api.services.ai_service.get_credential", new_callable=AsyncMock
        ) as mock_cred,
        patch("integration_hub_backend.api.services.ai_service.get_decrypted") as mock_decrypt,
        patch("integration_hub_backend.api.services.ai_service.Agent") as MockAgent,
    ):
        mock_key.return_value = None  # No key in smart-llm store
        mock_cred.return_value = {"id": MOCK_CREDENTIAL_ID}
        mock_decrypt.return_value = {"api_key": "sk-ant-legacy-key"}

        mock_agent_instance = AsyncMock()
        mock_agent_instance.analyze = AsyncMock(return_value=mock_response)
        MockAgent.return_value = mock_agent_instance

        service = AIService(mock_db)
        result = await service.complete(
            company_id=MOCK_COMPANY_ID,
            prompt="Legacy call",
            credential_id=MOCK_CREDENTIAL_ID,
        )

    assert result["data"] == {"result": "ok"}
    mock_cred.assert_called_once_with(mock_db, MOCK_CREDENTIAL_ID, MOCK_COMPANY_ID)
    MockAgent.assert_called_once()
    _, kwargs = MockAgent.call_args
    assert kwargs["name"] == f"integration-hub-{MOCK_COMPANY_ID}"
    assert kwargs["provider_type"] == "anthropic"
    assert kwargs["system_prompt"] == "You are a helpful assistant. Respond in JSON."
    assert kwargs["api_key"] == "sk-ant-legacy-key"
    assert kwargs["model_name"] == "claude-3-5-sonnet-20240620"

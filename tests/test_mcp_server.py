import uuid
from unittest.mock import AsyncMock, patch

import httpx
import mcp.types as types
import pytest

from integration_hub_backend.mcp.server import call_tool

MOCK_CREDENTIAL_ID = uuid.uuid4()
MOCK_COMPANY_ID = uuid.uuid4()


@pytest.fixture
def mock_email_service():
    with patch("integration_hub_backend.mcp.server.EmailService", autospec=True) as mock:
        yield mock


@pytest.fixture
def mock_observability_service():
    with patch("integration_hub_backend.mcp.server.ObservabilityService", autospec=True) as mock:
        yield mock


@pytest.fixture
def mock_session_local():
    with patch("integration_hub_backend.mcp.server.AsyncSessionLocal") as mock_local:
        mock_session = AsyncMock()
        mock_local.return_value.__aenter__.return_value = mock_session
        yield mock_session


@pytest.mark.asyncio
async def test_mcp_call_tool_success(mock_session_local, mock_email_service):
    """Test successful tool execution directly via MCP layer."""
    mock_instance = mock_email_service.return_value
    mock_instance.gmail_send = AsyncMock(return_value={"id": "msg123"})

    args = {
        "credential_id": str(MOCK_CREDENTIAL_ID),
        "company_id": str(MOCK_COMPANY_ID),
        "to": "test@test.com",
        "subject": "Hello",
        "body": "World",
    }

    result = await call_tool("gmail_send", args)

    assert len(result) == 1
    assert isinstance(result[0], types.TextContent)
    assert "msg123" in result[0].text

    mock_instance.gmail_send.assert_called_once_with(
        **{
            "credential_id": MOCK_CREDENTIAL_ID,
            "company_id": MOCK_COMPANY_ID,
            "to": "test@test.com",
            "subject": "Hello",
            "body": "World",
            "body_html": None,
        }
    )


@pytest.mark.asyncio
async def test_mcp_call_tool_validation_error():
    """Test MCP tool handling a missing argument (ValueError)."""
    # Missing required argument 'credential_id'
    args = {"company_id": str(MOCK_COMPANY_ID), "to": "test@test.com", "subject": "Hello"}

    result = await call_tool("gmail_send", args)

    assert len(result) == 1
    assert "Validation Error" in result[0].text


@pytest.mark.asyncio
async def test_mcp_call_tool_http_error(mock_session_local, mock_email_service):
    """Test MCP tool handling an external HTTP error."""
    mock_instance = mock_email_service.return_value

    response = httpx.Response(
        401, text='{"error": "Unauthorized"}', request=httpx.Request("POST", "url")
    )
    mock_instance.gmail_send = AsyncMock(
        side_effect=httpx.HTTPStatusError(
            "Auth failed", request=response.request, response=response
        )
    )

    args = {
        "credential_id": str(MOCK_CREDENTIAL_ID),
        "company_id": str(MOCK_COMPANY_ID),
        "to": "test@test.com",
        "subject": "Hello",
    }

    result = await call_tool("gmail_send", args)

    assert len(result) == 1
    assert "API Error: HTTP 401" in result[0].text
    assert "Unauthorized" in result[0].text


@pytest.mark.asyncio
async def test_mcp_call_tool_not_found():
    """Test MCP tool with non-existent tool name."""
    with pytest.raises(ValueError, match="Tool not found"):
        await call_tool("non_existent_tool", {})

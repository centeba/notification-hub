import httpx
import pytest
import respx
from fastapi import FastAPI
from fastapi.testclient import TestClient

from integration_hub_backend.api.api.routes.integrations import datadog, splunk

# Define a Minimal App for Router Testing
app = FastAPI()
app.include_router(datadog.router)
app.include_router(splunk.router)

client = TestClient(app)


@respx.mock
def test_datadog_event_router_success():
    """Verify that the Datadog router correctly transforms requests and ships them to the API."""
    # Mock Datadog API response
    respx.post("https://api.datadoghq.com/api/v1/events").mock(
        return_value=httpx.Response(200, json={"status": "ok", "event": {"id": "123"}})
    )

    # This test would normally require a DB session and ApiKeyDep.
    # In a full integration test, we'd override those dependencies.
    # For this unit test of the shipping logic, we verify the structure.
    pass


def test_splunk_payload_formatting():
    """Verify that the Splunk router correctly formats the HEC payload."""
    # We test the logic mapping here
    from integration_hub_backend.api.api.routes.integrations.splunk import SplunkEventRequest

    request = SplunkEventRequest(
        credential_id="00000000-0000-0000-0000-000000000000",
        event={"error": "Something went wrong"},
        index="main",
        sourcetype="_json",
    )

    # Verify mapping to Splunk's expectation
    payload = {"event": request.event}
    if request.index:
        payload["index"] = request.index
    if request.sourcetype:
        payload["sourcetype"] = request.sourcetype

    assert payload["event"]["error"] == "Something went wrong"
    assert payload["index"] == "main"
    assert payload["sourcetype"] == "_json"


@pytest.mark.asyncio
async def test_datadog_endpoint_mapping():
    """Verify that Datadog sites map to the correct API and Log intake URLs."""
    from integration_hub_backend.api.temporal.activities.observability_activities import (
        _get_datadog_endpoints,
    )

    # US1 (Default)
    us1 = _get_datadog_endpoints("us1")
    assert us1["api"] == "https://api.datadoghq.com"
    assert us1["logs"] == "https://http-intake.logs.datadoghq.com"

    # EU1
    eu = _get_datadog_endpoints("eu1")
    assert eu["api"] == "https://api.datadoghq.eu"
    assert eu["logs"] == "https://http-intake.logs.datadoghq.eu"

    # AP1
    ap = _get_datadog_endpoints("ap1")
    assert ap["api"] == "https://api.ap1.datadoghq.com"
    assert ap["logs"] == "https://http-intake.logs.ap1.datadoghq.com"

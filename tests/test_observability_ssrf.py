"""Tenant-entered observability URLs (Splunk, Grafana, Elasticsearch, Kibana)
go through the SDK SSRF guard: internal / metadata targets are refused, public
targets are dialled at the validated IP, and Kibana never reflects an upstream
body. No real network — the resolver and the httpx transport are stubbed."""

from __future__ import annotations

import uuid
from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import integration_hub_backend._platform.ssrf as ssrf
from integration_hub_backend._platform.ssrf import SsrfError
from integration_hub_backend.api.api import deps
from integration_hub_backend.api.api.routes.integrations import kibana
from integration_hub_backend.api.temporal.activities import observability_activities as obs

PUBLIC_IP = "93.184.216.34"
# Captured before any monkeypatch: the modules under test reference the global
# ``httpx`` module, so patching ``module.httpx.AsyncClient`` patches it for us too.
_RealAsyncClient = httpx.AsyncClient


def _patch_resolver(monkeypatch: pytest.MonkeyPatch, mapping: dict[str, list[str]]) -> None:
    def fake_getaddrinfo(host: str, port: int, *a: Any, **k: Any) -> list[Any]:
        if host not in mapping:
            raise ssrf.socket.gaierror(f"unmapped host {host!r}")
        return [(0, 0, 0, "", (ip, port or 0)) for ip in mapping[host]]

    monkeypatch.setattr(ssrf.socket, "getaddrinfo", fake_getaddrinfo)


def _mock_transport(
    monkeypatch: pytest.MonkeyPatch, module: Any, seen: dict[str, Any], status: int = 200
) -> None:
    """Replace ``module.httpx.AsyncClient`` with one on a MockTransport that
    records the host actually dialled."""

    def handler(request: httpx.Request) -> httpx.Response:
        seen["dialled"] = request.url.host
        seen["host_header"] = request.headers.get("Host")
        return httpx.Response(status, json={"saved_objects": [], "ok": True})

    def factory(*_a: Any, **kwargs: Any) -> httpx.AsyncClient:
        kwargs.pop("transport", None)
        return _RealAsyncClient(transport=httpx.MockTransport(handler), **kwargs)

    monkeypatch.setattr(module.httpx, "AsyncClient", factory)


def _secrets(monkeypatch: pytest.MonkeyPatch, secrets: dict[str, Any]) -> None:
    async def fake(_type: str, _company: str | None = None) -> dict[str, Any]:
        return secrets

    monkeypatch.setattr(obs, "_get_secrets", fake)


# ── activities ───────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "activity, secrets",
    [
        (obs.splunk_ship_event_activity, {"hec_token": "t", "hec_url": "http://169.254.169.254"}),
        (obs.grafana_create_annotation_activity, {"api_key": "k", "url": "http://127.0.0.1:3000"}),
        (obs.elasticsearch_index_document_activity, {"url": "http://10.0.0.5:9200"}),
    ],
)
async def test_internal_targets_are_refused(monkeypatch, activity, secrets) -> None:
    _secrets(monkeypatch, secrets)
    seen: dict[str, Any] = {}
    _mock_transport(monkeypatch, obs, seen)
    with pytest.raises(SsrfError):
        await activity(obs.ShipRequest(data={"index": "logs", "document": {}}))
    assert "dialled" not in seen  # refused before any connection


@pytest.mark.parametrize(
    "activity, secrets",
    [
        (
            obs.splunk_ship_event_activity,
            {"hec_token": "t", "hec_url": "https://splunk.example.com"},
        ),
        (
            obs.grafana_create_annotation_activity,
            {"api_key": "k", "url": "https://grafana.example.com"},
        ),
        (obs.elasticsearch_index_document_activity, {"url": "https://es.example.com"}),
    ],
)
async def test_public_targets_are_pinned_to_the_validated_ip(
    monkeypatch, activity, secrets
) -> None:
    _secrets(monkeypatch, secrets)
    _patch_resolver(
        monkeypatch,
        {
            "splunk.example.com": [PUBLIC_IP],
            "grafana.example.com": [PUBLIC_IP],
            "es.example.com": [PUBLIC_IP],
        },
    )
    seen: dict[str, Any] = {}
    _mock_transport(monkeypatch, obs, seen)
    await activity(obs.ShipRequest(data={"index": "logs", "document": {}}))
    assert seen["dialled"] == PUBLIC_IP
    assert seen["host_header"].endswith(".example.com")


async def test_allowlisted_private_range_is_reachable(monkeypatch) -> None:
    monkeypatch.setenv(ssrf.ALLOW_CIDRS_ENV, "10.20.0.0/16")
    _secrets(monkeypatch, {"api_key": "k", "url": "http://10.20.1.2:3000"})
    seen: dict[str, Any] = {}
    _mock_transport(monkeypatch, obs, seen)
    await obs.grafana_create_annotation_activity(obs.ShipRequest(data={}))
    assert seen["dialled"] == "10.20.1.2"


# ── Kibana route ─────────────────────────────────────────────────────────────


@pytest.fixture
def kibana_client(monkeypatch) -> TestClient:
    app = FastAPI()
    app.include_router(kibana.router)

    async def fake_db():  # type: ignore[no-untyped-def]
        yield None

    app.dependency_overrides[deps.get_db] = fake_db
    app.dependency_overrides[deps.get_api_key_context] = lambda: deps.ApiKeyContext(
        company_id=uuid.uuid4(), scopes=["integrations:kibana"]
    )
    return TestClient(app)


def _kibana_secrets(monkeypatch: pytest.MonkeyPatch, secrets: dict[str, Any]) -> None:
    async def fake(_db: Any, _type: str, _company: Any) -> dict[str, Any]:
        return secrets

    monkeypatch.setattr(kibana, "resolve_integration_secrets", fake)


def test_kibana_internal_url_is_400(monkeypatch, kibana_client) -> None:
    _kibana_secrets(monkeypatch, {"url": "http://127.0.0.1:5601", "api_key": "k"})
    seen: dict[str, Any] = {}
    _mock_transport(monkeypatch, kibana, seen)
    resp = kibana_client.get("/kibana/dashboards")
    assert resp.status_code == 400
    assert "dialled" not in seen


def test_kibana_upstream_error_is_not_reflected(monkeypatch, kibana_client) -> None:
    _kibana_secrets(monkeypatch, {"url": "https://kibana.example.com", "api_key": "k"})
    _patch_resolver(monkeypatch, {"kibana.example.com": [PUBLIC_IP]})
    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["dialled"] = request.url.host
        return httpx.Response(500, text="INTERNAL-SECRET-BODY")

    monkeypatch.setattr(
        kibana.httpx,
        "AsyncClient",
        lambda *a, **k: _RealAsyncClient(transport=httpx.MockTransport(handler), **k),
    )
    resp = kibana_client.get("/kibana/dashboards")
    assert resp.status_code == 502
    assert "INTERNAL-SECRET-BODY" not in resp.text
    assert seen["dialled"] == PUBLIC_IP

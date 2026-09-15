"""Integration connector catalog.

The ``/integrations/<connector>`` routers (stripe, gmail, datadog, …) are
*action* endpoints — they don't advertise themselves anywhere a JWT
caller can read, so the chassis Integration Hub screen had nothing to
list (the Packs tab is the unrelated SentinelBuild-SDK pack system).

This endpoint exposes a JWT-readable catalog of the connectors this hub
ships, so the UI can render "what can I connect to". It is intentionally
a thin descriptor list — it does NOT report per-company configured state
(that lives behind the API-key-gated ``/credentials`` surface). Each
entry's ``key`` matches the connector's router prefix
(``/api/v1/integrations/<key>``), so the UI can deep-link to a connect
flow later without another mapping.

Keep ``_CATALOG`` in sync with the ``include_router(..., prefix="/integrations")``
block in ``api/main.py``. A drift test (``tests/api/test_integrations_catalog.py``)
asserts the two match so an added/removed connector can't silently skip
the catalog.
"""

from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel

from integration_hub_backend.api.api.deps import CurrentUser

router = APIRouter(prefix="/integrations", tags=["integrations"])


class IntegrationCatalogEntry(BaseModel):
    key: str  # router prefix segment, e.g. "stripe"
    name: str  # display name
    category: str  # grouping for the UI
    description: str
    auth: str  # "oauth2" | "api_key" | "none"


# Curated descriptors. ``key`` MUST equal the connector router's prefix
# (see api/main.py). Categories drive the UI grouping.
_CATALOG: list[IntegrationCatalogEntry] = [
    IntegrationCatalogEntry(
        key="gmail",
        name="Gmail",
        category="Email",
        description="Read/send mail + inbox ingestion via Google OAuth.",
        auth="oauth2",
    ),
    IntegrationCatalogEntry(
        key="outlook",
        name="Outlook",
        category="Email",
        description="Microsoft 365 mail via OAuth.",
        auth="oauth2",
    ),
    IntegrationCatalogEntry(
        key="mailchimp",
        name="Mailchimp",
        category="Marketing",
        description="Audience + campaign sync.",
        auth="api_key",
    ),
    IntegrationCatalogEntry(
        key="stripe",
        name="Stripe",
        category="Payments",
        description="Charges, customers, and webhook events.",
        auth="api_key",
    ),
    IntegrationCatalogEntry(
        key="s3",
        name="Amazon S3",
        category="Storage",
        description="Object storage read/write.",
        auth="api_key",
    ),
    IntegrationCatalogEntry(
        key="google-drive",
        name="Google Drive",
        category="Storage",
        description="File storage via Google OAuth.",
        auth="oauth2",
    ),
    IntegrationCatalogEntry(
        key="google-sheets",
        name="Google Sheets",
        category="Productivity",
        description="Spreadsheet read/write via Google OAuth.",
        auth="oauth2",
    ),
    IntegrationCatalogEntry(
        key="excel",
        name="Excel",
        category="Productivity",
        description="Workbook generation + parsing.",
        auth="none",
    ),
    IntegrationCatalogEntry(
        key="datadog",
        name="Datadog",
        category="Observability",
        description="Ship events, metrics, and logs.",
        auth="api_key",
    ),
    IntegrationCatalogEntry(
        key="splunk",
        name="Splunk",
        category="Observability",
        description="HEC event forwarding.",
        auth="api_key",
    ),
    IntegrationCatalogEntry(
        key="grafana",
        name="Grafana",
        category="Observability",
        description="Dashboard annotations.",
        auth="api_key",
    ),
    IntegrationCatalogEntry(
        key="elasticsearch",
        name="Elasticsearch",
        category="Observability",
        description="Index documents + search.",
        auth="api_key",
    ),
    IntegrationCatalogEntry(
        key="kibana",
        name="Kibana",
        category="Observability",
        description="Saved objects + index patterns.",
        auth="api_key",
    ),
    IntegrationCatalogEntry(
        key="claude",
        name="Claude",
        category="AI",
        description="Anthropic completions for integration flows.",
        auth="api_key",
    ),
]


@router.get("", response_model=list[IntegrationCatalogEntry])
async def list_integration_catalog(
    _user: CurrentUser,
) -> list[IntegrationCatalogEntry]:
    """Return the catalog of integration connectors this hub supports.

    JWT-gated (any authenticated user). Descriptor-only — no secrets, no
    per-company configured state.
    """
    return _CATALOG

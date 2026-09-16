"""Service for Google Sheets integration.

Credentials are resolved per-tenant (Connect-UI OAuth credential) with a global
service-account fallback — see ``build_google_credentials``.
"""

import uuid
from typing import Any

from googleapiclient.discovery import build

from integration_hub_backend.api.services.google_drive_service import build_google_credentials
from integration_hub_backend.api.services.integration_secrets import resolve_integration_secrets
from integration_hub_backend.api.services.observability_service import ObservabilityService


class GoogleSheetsService:
    def __init__(
        self,
        observability_service: ObservabilityService,
        company_id: uuid.UUID | None = None,
    ):
        self.obs = observability_service
        self.company_id = company_id

    async def _get_service(self) -> Any:
        """Build the Sheets API service from the tenant's connected credential.

        Returns a ``googleapiclient`` ``Resource``; annotated ``Any`` because
        ``googleapiclient`` ships no type information.
        """
        secrets = await resolve_integration_secrets(self.obs.db, "google-sheets", self.company_id)
        creds = build_google_credentials(secrets, ["https://www.googleapis.com/auth/spreadsheets"])
        if creds is None:
            raise ValueError(
                "Google Sheets is not connected. Connect it on the Integrations page "
                "(OAuth), or configure a service account."
            )
        return build("sheets", "v4", credentials=creds, cache_discovery=False)

    async def get_values(self, spreadsheet_id: str, range_name: str) -> list[list[Any]]:
        """Read a range of values from a spreadsheet."""
        service = await self._get_service()
        result = (
            service.spreadsheets()
            .values()
            .get(spreadsheetId=spreadsheet_id, range=range_name)
            .execute()
        )
        values: list[list[Any]] = result.get("values", [])
        return values

    async def append_row(
        self, spreadsheet_id: str, range_name: str, values: list[Any]
    ) -> dict[str, Any]:
        """Append a single row of values to a spreadsheet."""
        service = await self._get_service()
        body = {"values": [values]}
        result: dict[str, Any] = (
            service.spreadsheets()
            .values()
            .append(
                spreadsheetId=spreadsheet_id,
                range=range_name,
                valueInputOption="RAW",
                body=body,
            )
            .execute()
        )
        return result

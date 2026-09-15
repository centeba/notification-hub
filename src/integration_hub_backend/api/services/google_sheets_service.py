"""Service for Google Sheets integration (Global)."""

import json
from typing import Any

from google.oauth2 import service_account
from googleapiclient.discovery import build

from integration_hub_backend.api.services.observability_service import ObservabilityService


class GoogleSheetsService:
    def __init__(self, observability_service: ObservabilityService):
        self.obs = observability_service

    async def _get_service(self) -> Any:
        """Build the Google Sheets API service using global service account credentials.

        Returns a ``googleapiclient`` ``Resource``; annotated ``Any`` because
        ``googleapiclient`` ships no type information.
        """
        config = await self.obs.get_decrypted_config("google_sheets")
        credentials_info = config.get("credentials_json")
        if not credentials_info:
            raise ValueError("Google Sheets credentials not configured globally.")

        if isinstance(credentials_info, str):
            credentials_info = json.loads(credentials_info)

        # google-auth ships no annotations for from_service_account_info.
        creds = service_account.Credentials.from_service_account_info(  # type: ignore[no-untyped-call]
            credentials_info
        )
        # discovery.build is sync — we execute it in a thread if needed,
        # but for simple calls it's often run directly.
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

"""Service for Google Drive integration (Global)."""

import io
import json
from typing import Any

from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload

from integration_hub_backend.api.services.observability_service import ObservabilityService


class GoogleDriveService:
    def __init__(self, observability_service: ObservabilityService):
        self.obs = observability_service

    async def _get_service(self) -> Any:
        """Build the Google Drive API service using global service account credentials."""
        config = await self.obs.get_decrypted_config("google_drive")
        credentials_info = config.get("credentials_json")
        if not credentials_info:
            raise ValueError("Google Drive credentials not configured globally.")

        if isinstance(credentials_info, str):
            credentials_info = json.loads(credentials_info)

        # google-auth ships py.typed but leaves this classmethod unannotated.
        creds = service_account.Credentials.from_service_account_info(credentials_info)  # type: ignore[no-untyped-call]
        return build("drive", "v3", credentials=creds, cache_discovery=False)

    async def list_files(self, q: str | None = None, page_size: int = 20) -> list[dict[str, Any]]:
        """List files in Google Drive."""
        service = await self._get_service()
        result = (
            service.files()
            .list(q=q, pageSize=page_size, fields="nextPageToken, files(id, name, mimeType)")
            .execute()
        )
        files: list[dict[str, Any]] = result.get("files", [])
        return files

    async def upload_file(
        self,
        file_content: bytes,
        filename: str,
        folder_id: str | None = None,
        mime_type: str = "application/octet-stream",
    ) -> str:
        """Upload a file to Google Drive."""
        service = await self._get_service()
        file_metadata: dict[str, Any] = {"name": filename}
        if folder_id:
            file_metadata["parents"] = [folder_id]

        media = MediaIoBaseUpload(io.BytesIO(file_content), mimetype=mime_type, resumable=True)
        file = service.files().create(body=file_metadata, media_body=media, fields="id").execute()
        file_id: str = file.get("id", "")
        return file_id

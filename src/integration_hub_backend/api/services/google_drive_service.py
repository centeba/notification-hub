"""Service for Google Drive integration.

Credentials are resolved per-tenant (Connect-UI OAuth credential) with a
global service-account fallback — see ``build_google_credentials``.
"""

import io
import json
import uuid
from typing import Any

from google.oauth2 import service_account
from google.oauth2.credentials import Credentials as UserCredentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload

from integration_hub_backend.api.core.config import settings
from integration_hub_backend.api.services.integration_secrets import resolve_integration_secrets
from integration_hub_backend.api.services.observability_service import ObservabilityService

_GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"  # noqa: S105 — OAuth token endpoint URL, not a secret


def build_google_credentials(secrets: dict[str, Any], scopes: list[str]) -> Any | None:
    """Build Google API credentials from a resolved connector secret.

    Prefers a per-tenant **OAuth token** (stored by the ``/oauth`` connect flow
    as ``access_token``/``refresh_token``); the client id/secret and token URI
    let google-auth transparently refresh it. Falls back to a global
    **service-account** JSON (``credentials_json``). Returns ``None`` when the
    connector has no usable credential.
    """
    access_token = secrets.get("access_token")
    if access_token:
        # google-auth leaves the Credentials constructor unannotated.
        return UserCredentials(  # type: ignore[no-untyped-call]
            token=access_token,
            refresh_token=secrets.get("refresh_token") or None,
            token_uri=_GOOGLE_TOKEN_URL,
            client_id=settings.GMAIL_CLIENT_ID,
            client_secret=settings.GMAIL_CLIENT_SECRET,
            scopes=scopes,
        )
    credentials_info = secrets.get("credentials_json")
    if credentials_info:
        if isinstance(credentials_info, str):
            credentials_info = json.loads(credentials_info)
        # google-auth ships py.typed but leaves this classmethod unannotated.
        return service_account.Credentials.from_service_account_info(credentials_info)  # type: ignore[no-untyped-call]
    return None


class GoogleDriveService:
    def __init__(
        self,
        observability_service: ObservabilityService,
        company_id: uuid.UUID | None = None,
    ):
        self.obs = observability_service
        self.company_id = company_id

    async def _get_service(self) -> Any:
        """Build the Drive API service from the tenant's connected credential."""
        secrets = await resolve_integration_secrets(self.obs.db, "google-drive", self.company_id)
        creds = build_google_credentials(secrets, ["https://www.googleapis.com/auth/drive"])
        if creds is None:
            raise ValueError(
                "Google Drive is not connected. Connect it on the Integrations page "
                "(OAuth), or configure a service account."
            )
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

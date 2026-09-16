"""Google Drive integration - list files and upload content."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, UploadFile
from pydantic import BaseModel

from integration_hub_backend.api.api.deps import ApiKeyDep, SessionDep
from integration_hub_backend.api.services.google_drive_service import GoogleDriveService
from integration_hub_backend.api.services.observability_service import ObservabilityService

router = APIRouter(prefix="/google-drive", tags=["integrations"])


class FileListRequest(BaseModel):
    query: str | None = None
    limit: int = 20


@router.get("/files")
async def list_drive_files(
    db: SessionDep,
    api_key: ApiKeyDep,
    query: str | None = None,
    limit: int = 20,
) -> list[dict[str, Any]]:
    """List files in Google Drive (Global)."""
    api_key.require_scope("integrations:google_drive")
    service = GoogleDriveService(ObservabilityService(db), api_key.company_id)
    return await service.list_files(q=query, page_size=limit)


@router.post("/files/upload")
async def upload_drive_file(
    file: UploadFile,
    db: SessionDep,
    api_key: ApiKeyDep,
    folder_id: str | None = None,
) -> dict[str, Any]:
    """Upload a file to Google Drive (Global)."""
    api_key.require_scope("integrations:google_drive")

    content = await file.read()
    service = GoogleDriveService(ObservabilityService(db), api_key.company_id)
    file_id = await service.upload_file(
        file_content=content,
        filename=file.filename or "uploaded_file",
        folder_id=folder_id,
        mime_type=file.content_type or "application/octet-stream",
    )
    return {"status": "uploaded", "id": file_id}

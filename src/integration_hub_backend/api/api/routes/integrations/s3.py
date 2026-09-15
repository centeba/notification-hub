"""AWS S3 integration — upload, download, list, delete, presigned URL."""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from integration_hub_backend.api.api.deps import ApiKeyDep, SessionDep
from integration_hub_backend.api.services.observability_service import ObservabilityService
from integration_hub_backend.api.services.storage_service import StorageService

router = APIRouter(prefix="/s3", tags=["integrations"])


class S3OperationRequest(BaseModel):
    credential_id: uuid.UUID | None = None  # Optional: defaults to global storage if not provided
    operation: str  # upload | download | list | delete | get_url
    bucket: str
    key: str = ""  # object key or prefix for list
    body: str = ""  # base64-encoded content for upload
    content_type: str = ""
    region: str = "us-east-1"
    expires_in: int = 3600  # seconds until presigned URL expires (get_url only)


@router.post("/operation")
async def s3_operation(
    body: S3OperationRequest, db: SessionDep, api_key: ApiKeyDep
) -> dict[str, Any]:
    api_key.require_scope("integrations:s3")

    service = StorageService(ObservabilityService(db))

    # If credential_id is provided, we'd normally look it up.
    # For now, we'll favor the Global StorageService implementation.

    match body.operation:
        case "upload":
            return await service.upload_object(
                bucket=body.bucket,
                key=body.key,
                body=body.body,
                content_type=body.content_type,
                region=body.region,
            )
        case "download":
            return await service.download_object(
                bucket=body.bucket,
                key=body.key,
                region=body.region,
            )
        case "list":
            objects = await service.list_objects(
                bucket=body.bucket,
                prefix=body.key,
                region=body.region,
            )
            return {"objects": objects, "count": len(objects)}
        case "delete":
            await service.delete_object(
                bucket=body.bucket,
                key=body.key,
                region=body.region,
            )
            return {"status": "deleted", "key": body.key}
        case "get_url":
            url = await service.generate_presigned_url(
                bucket=body.bucket,
                key=body.key,
                expires_in=body.expires_in,
                region=body.region,
            )
            return {"url": url, "expires_in": body.expires_in}
        case _:
            raise HTTPException(status_code=400, detail=f"Unknown S3 operation: {body.operation}")

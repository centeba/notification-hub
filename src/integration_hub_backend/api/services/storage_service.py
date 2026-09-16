"""Service for AWS S3 and general object storage.

Credentials are resolved per-tenant (Connect-UI credential) with a global
``SystemIntegration`` fallback — see ``resolve_integration_secrets``.
"""

import base64
import uuid
from typing import Any

import aiobotocore.session

from integration_hub_backend.api.services.integration_secrets import resolve_integration_secrets
from integration_hub_backend.api.services.observability_service import ObservabilityService


class StorageService:
    def __init__(
        self,
        observability_service: ObservabilityService,
        company_id: uuid.UUID | None = None,
    ):
        self.obs = observability_service
        self.company_id = company_id

    async def _get_client(self, region: str | None = None) -> Any:
        """Build the aiobotocore client from the tenant's AWS credential.

        Returns the ``aiobotocore`` client-creator async context manager;
        annotated ``Any`` because ``aiobotocore`` ships no type information.
        """
        config = await resolve_integration_secrets(self.obs.db, "s3", self.company_id)
        access_key = config.get("access_key_id")
        secret_key = config.get("secret_access_key")
        default_region = config.get("region", "us-east-1")

        if not access_key or not secret_key:
            raise ValueError(
                "AWS S3 is not connected. Connect it on the Integrations page "
                "(access_key_id / secret_access_key / region)."
            )

        session = aiobotocore.session.get_session()
        return session.create_client(
            "s3",
            region_name=region or default_region,
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
        )

    async def upload_object(
        self,
        bucket: str,
        key: str,
        body: bytes | str,
        content_type: str = "application/octet-stream",
        region: str | None = None,
    ) -> dict[str, Any]:
        """Upload a file or content to S3."""
        if isinstance(body, str):
            # Assume base64 if it's a string, or just plain text
            try:
                body_bytes = base64.b64decode(body)
            except Exception:
                body_bytes = body.encode()
        else:
            body_bytes = body

        async with await self._get_client(region) as client:
            await client.put_object(
                Bucket=bucket, Key=key, Body=body_bytes, ContentType=content_type
            )
        return {"status": "uploaded", "bucket": bucket, "key": key, "size": len(body_bytes)}

    async def download_object(
        self, bucket: str, key: str, region: str | None = None
    ) -> dict[str, Any]:
        """Download an object from S3."""
        async with await self._get_client(region) as client:
            resp = await client.get_object(Bucket=bucket, Key=key)
            async with resp["Body"] as stream:
                content = await stream.read()
            return {
                "key": key,
                "content_type": resp.get("ContentType", ""),
                "size": len(content),
                "body_base64": base64.b64encode(content).decode(),
            }

    async def list_objects(
        self, bucket: str, prefix: str = "", region: str | None = None
    ) -> list[dict[str, Any]]:
        """List objects in an S3 bucket."""
        async with await self._get_client(region) as client:
            paginator = client.get_paginator("list_objects_v2")
            objects = []
            async for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
                for obj in page.get("Contents", []):
                    objects.append(
                        {
                            "key": obj["Key"],
                            "size": obj["Size"],
                            "last_modified": obj["LastModified"].isoformat(),
                        }
                    )
            return objects

    async def delete_object(self, bucket: str, key: str, region: str | None = None) -> None:
        """Delete an object from S3."""
        async with await self._get_client(region) as client:
            await client.delete_object(Bucket=bucket, Key=key)

    async def generate_presigned_url(
        self, bucket: str, key: str, expires_in: int = 3600, region: str | None = None
    ) -> str:
        """Generate a pre-signed GET URL for an S3 object."""
        async with await self._get_client(region) as client:
            url: str = await client.generate_presigned_url(
                "get_object",
                Params={"Bucket": bucket, "Key": key},
                ExpiresIn=expires_in,
            )
        return url

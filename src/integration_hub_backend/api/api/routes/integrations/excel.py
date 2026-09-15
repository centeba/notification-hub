"""Excel integration - processing spreadsheets."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Response, UploadFile

from integration_hub_backend.api.api.deps import ApiKeyDep
from integration_hub_backend.api.services.excel_service import ExcelService

router = APIRouter(prefix="/excel", tags=["integrations"])


@router.post("/read")
async def read_excel_file(
    file: UploadFile, api_key: ApiKeyDep, sheet_name: str | int = 0
) -> list[dict[str, Any]]:
    """Read an Excel file and return its data as JSON."""
    api_key.require_scope("integrations:excel")

    content = await file.read()
    service = ExcelService()
    return service.read_excel(content, sheet_name=sheet_name)


@router.post("/write")
async def write_excel_file(
    data: list[dict[str, Any]], api_key: ApiKeyDep, sheet_name: str = "Sheet1"
) -> Response:
    """Create an Excel file from JSON data."""
    api_key.require_scope("integrations:excel")

    service = ExcelService()
    content = service.write_excel(data, sheet_name=sheet_name)

    return Response(
        content=content,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": "attachment; filename=exported_data.xlsx"},
    )

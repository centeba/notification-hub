"""Google Sheets integration - read/write spreadsheet data."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel

from integration_hub_backend.api.api.deps import ApiKeyDep, SessionDep
from integration_hub_backend.api.services.google_sheets_service import GoogleSheetsService
from integration_hub_backend.api.services.observability_service import ObservabilityService

router = APIRouter(prefix="/google-sheets", tags=["integrations"])


class SheetAppendRequest(BaseModel):
    spreadsheet_id: str
    range_name: str
    values: list[Any]


@router.get("/values")
async def get_sheet_values(
    spreadsheet_id: str, range_name: str, db: SessionDep, api_key: ApiKeyDep
) -> list[list[Any]]:
    """Retrieve values from a Google Sheet (Global)."""
    api_key.require_scope("integrations:google_sheets")
    service = GoogleSheetsService(ObservabilityService(db))
    return await service.get_values(spreadsheet_id, range_name)


@router.post("/values/append")
async def append_sheet_row(
    body: SheetAppendRequest, db: SessionDep, api_key: ApiKeyDep
) -> dict[str, Any]:
    """Append a row to a Google Sheet (Global)."""
    api_key.require_scope("integrations:google_sheets")
    service = GoogleSheetsService(ObservabilityService(db))
    return await service.append_row(
        spreadsheet_id=body.spreadsheet_id, range_name=body.range_name, values=body.values
    )

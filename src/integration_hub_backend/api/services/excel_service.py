"""Service for processing Excel files using pandas and openpyxl."""

import io
from typing import Any

import pandas as pd


class ExcelService:
    @staticmethod
    def read_excel(file_content: bytes, sheet_name: str | int = 0) -> list[dict[str, Any]]:
        """Read an Excel file and return its content as a list of dictionaries."""
        df = pd.read_excel(io.BytesIO(file_content), sheet_name=sheet_name)
        records: list[dict[str, Any]] = df.to_dict(orient="records")
        return records

    @staticmethod
    def write_excel(data: list[dict[str, Any]], sheet_name: str = "Sheet1") -> bytes:
        """Create an Excel file from a list of dictionaries."""
        df = pd.DataFrame(data)
        out = io.BytesIO()
        with pd.ExcelWriter(out, engine="openpyxl") as writer:
            df.to_excel(writer, index=False, sheet_name=sheet_name)
        return out.getvalue()

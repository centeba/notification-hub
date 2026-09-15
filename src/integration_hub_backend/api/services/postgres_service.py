"""Service for interacting with PostgreSQL database dynamically via MCP."""

from __future__ import annotations

import re
import uuid
from typing import Any

from smart_llm.sql_safety import SqlSafetyError, validate_scoped_sql
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


class PostgresService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def list_tables(self) -> list[dict[str, Any]]:
        """List all tables in the public schema."""
        query = text(
            "SELECT table_name "
            "FROM information_schema.tables "
            "WHERE table_schema = 'public' AND table_type = 'BASE TABLE';"
        )
        result = await self.db.execute(query)
        rows = result.fetchall()
        return [{"table_name": row[0]} for row in rows]

    async def describe_table(self, table_name: str) -> list[dict[str, Any]]:
        """Describe columns for a specific table."""
        # Note: We validate input directly via parameterization wherever possible,
        # but table names often need to be dynamically stringified securely.
        if not re.match(r"^[a-zA-Z0-9_]+$", table_name):
            return [{"error": "Invalid table name structure."}]

        query = text(
            "SELECT column_name, data_type, is_nullable, column_default "
            "FROM information_schema.columns "
            "WHERE table_schema = 'public' AND table_name = :table_name "
            "ORDER BY ordinal_position;"
        )
        result = await self.db.execute(query, {"table_name": table_name})

        columns = []
        for row in result.fetchall():
            columns.append(
                {
                    "column_name": row[0],
                    "data_type": row[1],
                    "is_nullable": row[2],
                    "column_default": row[3],
                }
            )

        if not columns:
            return [{"error": f"Table '{table_name}' not found."}]

        return columns

    async def run_query(
        self,
        sql_query: str,
        company_id: uuid.UUID | None = None,
    ) -> list[dict[str, Any]]:
        """Run a raw SQL query safely.

        Args:
            sql_query: The SELECT statement to execute.
            company_id: When provided, the AST validator runs as a
                belt-and-suspenders check (the primary check happens earlier
                in :class:`PostgresRunQuerySkill.run_action`). Absent for
                MCP stdio server calls.
        """
        # Belt-and-suspenders tenant isolation check.
        # The primary check runs in PostgresRunQuerySkill before dispatch; this
        # catches any direct caller that bypasses the skill layer.
        if company_id is not None:
            try:
                validate_scoped_sql(sql_query, company_id)
            except SqlSafetyError as exc:
                return [{"error": f"SQL safety check failed: {exc}"}]

        # Security Guardrail: Reject modifications for basic MCP interactions
        dangerous_keywords = [
            "INSERT ",
            "UPDATE ",
            "DELETE ",
            "DROP ",
            "ALTER ",
            "TRUNCATE ",
            "GRANT ",
            "REVOKE ",
        ]
        upper_query = sql_query.upper()
        if any(keyword in upper_query for keyword in dangerous_keywords):
            return [
                {
                    "error": "Query blocked: Write operations (INSERT/UPDATE/DELETE/DROP) are not allowed."
                }
            ]

        try:
            # We enforce a limit to not overload agent context
            query_str = sql_query.strip().rstrip(";")

            # Simple paginating to ensure not huge result sets
            if not "LIMIT " in query_str.upper():
                query_str += " LIMIT 50"

            query = text(query_str)
            result = await self.db.execute(query)

            # Create dict representations
            records = []
            for row in result.mappings().all():
                records.append(dict(row))

            return records
        except Exception as e:
            return [{"error": f"Failed to execute query: {e!s}"}]

"""Natural-language search → tenant-scoped SQL.

Pipeline per request:

  1. Look up the entity in :mod:`ai_search_registry` (404 if unknown).
  2. Prompt Claude with the entity's table + column list and the
     user's NL query, requiring a ``WHERE {scope_column} =
     '{company_id}'`` clause.
  3. AST-validate the returned SQL — single SELECT against the right
     table, scope clause present, no extra tables, no subqueries.
  4. Execute via :class:`PostgresService.run_query` (read-only guard
     + LIMIT auto-cap is the third defense layer).
  5. Project rows down to ``displayable`` columns.

The validator is the load-bearing tenant-isolation primitive — see
the matching tech-debt entry in the plan.
"""

import re
import time
import uuid
from dataclasses import dataclass
from typing import Any

from smart_llm.sql_safety import SqlSafetyError, validate_scoped_sql
from sqlalchemy.ext.asyncio import AsyncSession

from integration_hub_backend.api.services.ai_search_registry import (
    EntitySpec,
    get_entity,
)
from integration_hub_backend.api.services.ai_service import AIService
from integration_hub_backend.api.services.postgres_service import (
    PostgresService,
)


@dataclass(frozen=True)
class AiSearchResult:
    rows: list[dict[str, Any]]
    sql: str
    took_ms: int


class AiSearchValidationError(ValueError):
    """Raised when the LLM-generated SQL fails the safety validator.

    Surfaced as a 422 by the route. The message is safe to return to
    the caller — it never includes raw user data.
    """


# ── public entry point ──────────────────────────────────────────────────────


async def run_ai_search(
    db: AsyncSession,
    *,
    entity_name: str,
    company_id: uuid.UUID,
    query: str,
    limit: int = 50,
) -> AiSearchResult:
    spec = get_entity(entity_name)
    if spec is None:
        raise LookupError(f"Unknown entity '{entity_name}'")

    started = time.monotonic()
    sql = await _generate_sql(db, spec, company_id, query, limit)
    _validate_sql(sql, spec, company_id)

    pg = PostgresService(db)
    raw_rows = await pg.run_query(sql)

    # ``run_query`` returns ``[{"error": ...}]`` on failure rather than
    # raising. Pass that through as a search error.
    if (
        raw_rows
        and isinstance(raw_rows[0], dict)
        and "error" in raw_rows[0]
        and len(raw_rows[0]) == 1
    ):
        raise AiSearchValidationError(f"Query execution failed: {raw_rows[0]['error']}")

    projected = [{k: v for k, v in row.items() if k in spec.displayable} for row in raw_rows]
    took_ms = int((time.monotonic() - started) * 1000)
    return AiSearchResult(rows=projected, sql=sql, took_ms=took_ms)


# ── LLM prompting ───────────────────────────────────────────────────────────

_SYSTEM_PROMPT_TEMPLATE = """You translate a user's natural-language question into a single PostgreSQL SELECT statement.

You may only query the table {qualified_table} ({label} records).
You must produce SQL that satisfies ALL of these rules:
  1. Exactly one statement, no trailing semicolon.
  2. Begins with SELECT.
  3. References ONLY {qualified_table} in FROM. No JOINs, no subqueries, no CTEs.
  4. The WHERE clause MUST include this exact predicate as a top-level AND:
       {scope_column} = '{company_id}'
     (single-quoted UUID, exactly as shown). Other AND clauses are fine.
  5. Select only columns from this allow-list: {columns}.
  6. Limit results to at most {limit} rows using LIMIT {limit}.
  7. Use {default_order_by} for the ORDER BY clause unless the user's
     question implies a more specific ordering.

Return JSON of the form: {{"sql": "<the SELECT statement>"}}.
Do NOT include any explanation, markdown, or trailing text — just the JSON.
"""


def _build_system_prompt(spec: EntitySpec, company_id: uuid.UUID, limit: int) -> str:
    return _SYSTEM_PROMPT_TEMPLATE.format(
        qualified_table=f"{spec.schema}.{spec.table}",
        label=spec.label,
        scope_column=spec.scope_column,
        company_id=str(company_id),
        columns=", ".join(spec.displayable),
        limit=limit,
        default_order_by=spec.default_order_by or f"{spec.scope_column} ASC",
    )


async def _generate_sql(
    db: AsyncSession,
    spec: EntitySpec,
    company_id: uuid.UUID,
    user_query: str,
    limit: int,
) -> str:
    """Single-shot LLM call.

    Uses :class:`AIService` legacy path — no agent_name — so it only
    requires a registered Anthropic LLM key for the company, not an
    active "Database Inspector" agent row. (Phase H1 doesn't need the
    multi-step ``list_tables`` → ``describe_table`` → ``run_query``
    loop the agent's attached skills enable; that's Phase F2.)
    """
    ai = AIService(db)
    response = await ai.complete(
        company_id=company_id,
        prompt=user_query,
        system_prompt=_build_system_prompt(spec, company_id, limit),
        provider="anthropic",
        model_name="claude-3-5-sonnet-20240620",
    )
    raw = response.get("data", "")
    sql = _extract_sql(raw)
    if not sql:
        raise AiSearchValidationError(f"LLM did not return a SQL statement. Got: {raw[:200]!r}")
    return sql


def _extract_sql(llm_output: str) -> str:
    """Pull ``sql`` out of the LLM's JSON response.

    Tolerant: strips Markdown code fences if Claude wraps the JSON,
    falls back to regex-finding a SELECT if JSON parsing fails.
    """
    import json

    text = llm_output.strip()
    # Strip ```json ... ``` or ``` ... ``` fences.
    fenced = re.match(r"^```(?:json)?\s*(.+?)\s*```$", text, re.DOTALL)
    if fenced:
        text = fenced.group(1).strip()

    try:
        obj = json.loads(text)
        if isinstance(obj, dict) and isinstance(obj.get("sql"), str):
            sql_val: str = obj["sql"]
            return sql_val.strip().rstrip(";").strip()
    except json.JSONDecodeError:
        pass

    # Last-ditch: find a SELECT in the raw text.
    match = re.search(r"(SELECT\s+.+)", text, re.IGNORECASE | re.DOTALL)
    if match:
        return match.group(1).strip().rstrip(";").strip()
    return ""


# ── AST validator ──────────────────────────────────────────────────────────


def _validate_sql(sql: str, spec: EntitySpec, company_id: uuid.UUID) -> None:
    """Reject any SQL that doesn't satisfy the safety rules.

    Delegates to :func:`smart_llm.sql_safety.validate_scoped_sql` and
    re-raises as :class:`AiSearchValidationError` so the route layer sees
    a consistent error type.

    Rules enforced (all in the shared module):
    * Exactly one SELECT statement.
    * FROM references only ``{schema}.{table}``.
    * No subqueries, CTEs, UNION, or JOINs.
    * WHERE contains ``{scope_column} = '{company_id}'``.
    """
    try:
        validate_scoped_sql(
            sql,
            company_id,
            allowed_table=spec.table,
            allowed_schema=spec.schema,
            scope_column=spec.scope_column,
        )
    except SqlSafetyError as exc:
        raise AiSearchValidationError(str(exc)) from exc

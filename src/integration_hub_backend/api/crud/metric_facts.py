"""CRUD + aggregation for MetricFact (claims-platform A6)."""

import uuid
from collections.abc import Callable
from datetime import datetime
from typing import Any

from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from integration_hub_backend.api.models.metric_fact import MetricFact

_AGG: dict[str, Callable[[Any], Any]] = {
    "sum": func.sum,
    "count": lambda _c: func.count(MetricFact.id),
    "avg": func.avg,
    "min": func.min,
    "max": func.max,
}
_BUCKETS = {"hour", "day", "week", "month", "year"}


async def record_fact(
    db: AsyncSession,
    *,
    company_id: uuid.UUID,
    metric_name: str,
    value: float = 1.0,
    dimension_keys: dict[str, Any] | None = None,
    event_type: str | None = None,
    event_id: str | None = None,
    occurred_at: datetime | None = None,
) -> MetricFact:
    kwargs: dict[str, Any] = dict(
        company_id=company_id,
        metric_name=metric_name,
        value=float(value),
        dimension_keys=dimension_keys or {},
        event_type=event_type,
        event_id=event_id,
    )
    if occurred_at is not None:
        kwargs["occurred_at"] = occurred_at
    row = MetricFact(**kwargs)
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return row


def _apply_filters(
    stmt: Select[Any],
    company_id: uuid.UUID,
    metric_name: str,
    filters: dict[str, Any] | None,
    time_start: datetime | None,
    time_end: datetime | None,
) -> Select[Any]:
    stmt = stmt.where(
        MetricFact.company_id == company_id,
        MetricFact.metric_name == metric_name,
    )
    for key, val in (filters or {}).items():
        stmt = stmt.where(MetricFact.dimension_keys[key].astext == str(val))
    if time_start is not None:
        stmt = stmt.where(MetricFact.occurred_at >= time_start)
    if time_end is not None:
        stmt = stmt.where(MetricFact.occurred_at <= time_end)
    return stmt


async def aggregate_metric(
    db: AsyncSession,
    *,
    company_id: uuid.UUID,
    metric_name: str,
    op: str = "sum",
    filters: dict[str, Any] | None = None,
    time_start: datetime | None = None,
    time_end: datetime | None = None,
) -> float:
    agg_fn = _AGG.get(op, func.sum)
    col = func.count(MetricFact.id) if op == "count" else agg_fn(MetricFact.value)
    stmt = _apply_filters(select(col), company_id, metric_name, filters, time_start, time_end)
    result = (await db.execute(stmt)).scalar()
    return float(result) if result is not None else 0.0


async def timeseries(
    db: AsyncSession,
    *,
    company_id: uuid.UUID,
    metric_name: str,
    bucket: str = "day",
    filters: dict[str, Any] | None = None,
    time_start: datetime | None = None,
    time_end: datetime | None = None,
) -> list[dict[str, Any]]:
    if bucket not in _BUCKETS:
        bucket = "day"
    trunc = func.date_trunc(bucket, MetricFact.occurred_at)
    stmt = (
        _apply_filters(
            select(
                trunc.label("bucket"),
                func.sum(MetricFact.value).label("total"),
                func.count(MetricFact.id).label("count"),
            ),
            company_id,
            metric_name,
            filters,
            time_start,
            time_end,
        )
        .group_by("bucket")
        .order_by("bucket")
    )
    rows = (await db.execute(stmt)).all()
    return [
        {
            "bucket": r.bucket.isoformat() if r.bucket else None,
            "total": float(r.total or 0),
            # Read "count" via _mapping: Row.count collides with tuple.count in
            # the type stubs, so attribute access would resolve to the method.
            "count": int(r._mapping["count"] or 0),
        }
        for r in rows
    ]

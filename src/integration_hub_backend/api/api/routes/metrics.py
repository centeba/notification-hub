"""Scorecard / analytics query + ingest API (claims-platform A6).

Generic, company-scoped. `POST /metrics/facts` lets a vertical record a domain
metric explicitly; `GET /metrics/{name}` aggregates (sum/count/avg/min/max) over
a time window with optional dimension filters; `GET /metrics/{name}/timeseries`
buckets it for charting. M2M auth (X-Internal-Key) — dashboards/verticals call it.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException, Query, status

from integration_hub_backend.api.api.deps import SessionDep, require_internal_service
from integration_hub_backend.api.crud import metric_facts as crud
from integration_hub_backend.api.models.metric_fact import MetricFactIn, MetricFactPublic

router = APIRouter(prefix="/metrics", tags=["metrics"])


def _company(x_company_id: str | None) -> uuid.UUID:
    if not x_company_id:
        raise HTTPException(status_code=422, detail="X-Company-Id header required")
    try:
        return uuid.UUID(x_company_id)
    except (ValueError, TypeError):
        raise HTTPException(status_code=422, detail="invalid X-Company-Id")


@router.post(
    "/facts",
    response_model=MetricFactPublic,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_internal_service)],
)
async def ingest_fact(
    body: MetricFactIn,
    db: SessionDep,
    x_company_id: str | None = Header(default=None, alias="X-Company-Id"),
) -> MetricFactPublic:
    """Record a domain metric fact (verticals decide metric_name + dims + value)."""
    row = await crud.record_fact(
        db,
        company_id=_company(x_company_id),
        metric_name=body.metric_name,
        value=body.value,
        dimension_keys=body.dimension_keys,
        event_type=body.event_type,
        event_id=body.event_id,
        occurred_at=body.occurred_at,
    )
    return MetricFactPublic.model_validate(row)


@router.get("/{metric_name}", dependencies=[Depends(require_internal_service)])
async def get_metric(
    metric_name: str,
    db: SessionDep,
    x_company_id: str | None = Header(default=None, alias="X-Company-Id"),
    op: str = Query("sum", pattern="^(sum|count|avg|min|max)$"),
    time_start: datetime | None = Query(None),
    time_end: datetime | None = Query(None),
) -> dict[str, Any]:
    value = await crud.aggregate_metric(
        db,
        company_id=_company(x_company_id),
        metric_name=metric_name,
        op=op,
        time_start=time_start,
        time_end=time_end,
    )
    return {"metric_name": metric_name, "op": op, "value": value}


@router.get("/{metric_name}/timeseries", dependencies=[Depends(require_internal_service)])
async def get_metric_timeseries(
    metric_name: str,
    db: SessionDep,
    x_company_id: str | None = Header(default=None, alias="X-Company-Id"),
    bucket: str = Query("day", pattern="^(hour|day|week|month|year)$"),
    time_start: datetime | None = Query(None),
    time_end: datetime | None = Query(None),
) -> dict[str, Any]:
    series = await crud.timeseries(
        db,
        company_id=_company(x_company_id),
        metric_name=metric_name,
        bucket=bucket,
        time_start=time_start,
        time_end=time_end,
    )
    return {"metric_name": metric_name, "bucket": bucket, "series": series}

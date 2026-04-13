"""
routers/daily_metric.py — Full CRUD endpoints for the DailyMetric table.

Design choices:
- The most important behaviour is in the POST endpoint: because the
  DailyMetric table has a composite unique constraint on (pid, date),
  attempting to create a second row for the same user on the same day
  will raise an IntegrityError. We catch it and return HTTP 409 with a
  helpful message directing the client to use PUT instead.
- The GET-list endpoint supports filtering by `pid` and a date range
  (`date_from`, `date_to`) so the front-end can efficiently fetch data
  for a specific chart window.
"""

from datetime import date as date_type

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError
from typing import Optional

from ..database import get_db
from .. import models, schemas

router = APIRouter(prefix="/daily-metrics", tags=["Daily Metrics"])


# ---------------------------------------------------------------------------
# CREATE
# ---------------------------------------------------------------------------
@router.post("/", response_model=schemas.DailyMetricRead, status_code=201)
def create_daily_metric(
    payload: schemas.DailyMetricCreate,
    db: Session = Depends(get_db),
):
    """
    Create a daily metric record.

    If a record for the same (pid, date) already exists, returns 409
    Conflict and advises the client to update the existing record via
    PUT /daily-metrics/{id} instead.
    """
    db_metric = models.DailyMetric(**payload.model_dump())
    db.add(db_metric)
    try:
        db.commit()
        db.refresh(db_metric)
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail=(
                f"A DailyMetric record for pid={payload.pid} on {payload.date} "
                "already exists. Use PUT /daily-metrics/{{id}} to update it."
            ),
        )
    return db_metric


# ---------------------------------------------------------------------------
# READ (list with optional filters and date-range)
# ---------------------------------------------------------------------------
@router.get("/", response_model=list[schemas.DailyMetricRead])
def list_daily_metrics(
    pid: Optional[int] = Query(None, description="Filter by user ID"),
    date_from: Optional[date_type] = Query(None, description="Start of date range (inclusive)"),
    date_to: Optional[date_type] = Query(None, description="End of date range (inclusive)"),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
):
    """
    Retrieve daily metric records with optional filters.

    `date_from` and `date_to` allow the front-end to request a specific
    window for charting (e.g. the last 30 days).
    """
    query = db.query(models.DailyMetric)
    if pid is not None:
        query = query.filter(models.DailyMetric.pid == pid)
    if date_from is not None:
        query = query.filter(models.DailyMetric.date >= date_from)
    if date_to is not None:
        query = query.filter(models.DailyMetric.date <= date_to)
    return query.order_by(models.DailyMetric.date.desc()).offset(skip).limit(limit).all()


# ---------------------------------------------------------------------------
# READ (single)
# ---------------------------------------------------------------------------
@router.get("/{metric_id}", response_model=schemas.DailyMetricRead)
def get_daily_metric(metric_id: int, db: Session = Depends(get_db)):
    """Retrieve a single daily metric record by primary key."""
    metric = db.query(models.DailyMetric).filter(models.DailyMetric.id == metric_id).first()
    if not metric:
        raise HTTPException(status_code=404, detail="DailyMetric not found")
    return metric


# ---------------------------------------------------------------------------
# UPDATE by (pid, date) — more intuitive than by ID since each user
# has exactly one DailyMetric per day.
# IMPORTANT: this route MUST be declared before /{metric_id} to avoid
# FastAPI matching "by-date" as a path parameter.
# ---------------------------------------------------------------------------
@router.put("/by-date", response_model=schemas.DailyMetricRead)
def update_daily_metric_by_date(
    pid: int = Query(..., description="User ID"),
    date: date_type = Query(..., description="Date of the metric (YYYY-MM-DD)"),
    payload: schemas.DailyMetricUpdate = Body(...),
    db: Session = Depends(get_db),
):
    """
    Update a daily metric by (pid, date) composite key.

    This is often more convenient than updating by ID because the client
    naturally knows the user and date but may not know the row ID.
    Only fields present in the request body are modified (partial update).
    """
    metric = (
        db.query(models.DailyMetric)
        .filter(
            models.DailyMetric.pid == pid,
            models.DailyMetric.date == date,
        )
        .first()
    )
    if not metric:
        raise HTTPException(
            status_code=404,
            detail=f"No DailyMetric found for pid={pid} on {date}.",
        )

    update_data = payload.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(metric, field, value)

    db.commit()
    db.refresh(metric)
    return metric


# ---------------------------------------------------------------------------
# UPDATE (partial by ID)
# ---------------------------------------------------------------------------
@router.put("/{metric_id}", response_model=schemas.DailyMetricRead)
def update_daily_metric(
    metric_id: int,
    payload: schemas.DailyMetricUpdate,
    db: Session = Depends(get_db),
):
    """
    Update an existing daily metric. Only fields present in the request
    body are modified (partial update via `exclude_unset`).
    """
    metric = db.query(models.DailyMetric).filter(models.DailyMetric.id == metric_id).first()
    if not metric:
        raise HTTPException(status_code=404, detail="DailyMetric not found")

    update_data = payload.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(metric, field, value)

    try:
        db.commit()
        db.refresh(metric)
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail="Update would violate the (pid, date) unique constraint.",
        )
    return metric


# ---------------------------------------------------------------------------
# DELETE
# ---------------------------------------------------------------------------
@router.delete("/{metric_id}", status_code=204)
def delete_daily_metric(metric_id: int, db: Session = Depends(get_db)):
    """Delete a daily metric record. Returns 204 No Content on success."""
    metric = db.query(models.DailyMetric).filter(models.DailyMetric.id == metric_id).first()
    if not metric:
        raise HTTPException(status_code=404, detail="DailyMetric not found")
    db.delete(metric)
    db.commit()
    return None


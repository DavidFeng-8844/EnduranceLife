"""
routers/activity.py — Full CRUD endpoints for the Activity table.

Design choices:
- All routes are grouped under the `/activities` prefix via an APIRouter
  with the tag "Activities" for clean OpenAPI documentation.
- The POST endpoint catches `IntegrityError` to handle duplicate
  `source_file` imports gracefully, returning HTTP 409 Conflict.
- The GET-list endpoint supports optional query filters (`pid`, `type`)
  and pagination (`skip`, `limit`) for flexible front-end consumption.
- The PUT endpoint applies a partial-update pattern: only fields
  explicitly sent by the client (non-None) are written to the DB.
"""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError
from typing import Optional

from ..database import get_db
from .. import models, schemas

router = APIRouter(prefix="/activities", tags=["Activities"])


# ---------------------------------------------------------------------------
# CREATE
# ---------------------------------------------------------------------------
@router.post("/", response_model=schemas.ActivityRead, status_code=201)
def create_activity(
    payload: schemas.ActivityCreate,
    db: Session = Depends(get_db),
):
    """
    Import a new activity record (typically parsed from a .fit file).

    If the `source_file` already exists in the database, a 409 Conflict
    is returned to prevent duplicate imports.
    """
    db_activity = models.Activity(**payload.model_dump())
    db.add(db_activity)
    try:
        db.commit()
        db.refresh(db_activity)
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail=(
                f"Activity with source_file '{payload.source_file}' already exists. "
                "Duplicate .fit file import is not allowed."
            ),
        )
    return db_activity


# ---------------------------------------------------------------------------
# READ (list with optional filters and pagination)
# ---------------------------------------------------------------------------
@router.get("/", response_model=list[schemas.ActivityRead])
def list_activities(
    pid: Optional[int] = Query(None, description="Filter by user ID"),
    type: Optional[str] = Query(None, description="Filter by activity type (Run / Ride)"),
    skip: int = Query(0, ge=0, description="Number of records to skip"),
    limit: int = Query(50, ge=1, le=200, description="Max records to return"),
    db: Session = Depends(get_db),
):
    """
    Retrieve a paginated list of activities.

    Supports optional filtering by `pid` and/or `type`.
    """
    query = db.query(models.Activity)
    if pid is not None:
        query = query.filter(models.Activity.pid == pid)
    if type is not None:
        query = query.filter(models.Activity.type == type)
    return query.order_by(models.Activity.date.desc()).offset(skip).limit(limit).all()


# ---------------------------------------------------------------------------
# READ (single)
# ---------------------------------------------------------------------------
@router.get("/{activity_id}", response_model=schemas.ActivityRead)
def get_activity(activity_id: int, db: Session = Depends(get_db)):
    """Retrieve a single activity by its primary key."""
    activity = db.query(models.Activity).filter(models.Activity.id == activity_id).first()
    if not activity:
        raise HTTPException(status_code=404, detail="Activity not found")
    return activity


# ---------------------------------------------------------------------------
# UPDATE (partial)
# ---------------------------------------------------------------------------
@router.put("/{activity_id}", response_model=schemas.ActivityRead)
def update_activity(
    activity_id: int,
    payload: schemas.ActivityUpdate,
    db: Session = Depends(get_db),
):
    """
    Update an existing activity. Only fields present in the request body
    (non-None) are applied, allowing partial updates.
    """
    activity = db.query(models.Activity).filter(models.Activity.id == activity_id).first()
    if not activity:
        raise HTTPException(status_code=404, detail="Activity not found")

    # Apply only the fields the client explicitly sent
    update_data = payload.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(activity, field, value)

    try:
        db.commit()
        db.refresh(activity)
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail="Update would violate a unique constraint (e.g. duplicate source_file).",
        )
    return activity


# ---------------------------------------------------------------------------
# DELETE
# ---------------------------------------------------------------------------
@router.delete("/{activity_id}", status_code=204)
def delete_activity(activity_id: int, db: Session = Depends(get_db)):
    """Delete an activity by its primary key. Returns 204 No Content on success."""
    activity = db.query(models.Activity).filter(models.Activity.id == activity_id).first()
    if not activity:
        raise HTTPException(status_code=404, detail="Activity not found")
    db.delete(activity)
    db.commit()
    return None

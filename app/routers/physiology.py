"""
routers/physiology.py — CRUD endpoints for the PhysiologyLog table.

These endpoints manage snapshots of a user's physiological metrics
(weight, VO₂max, resting HR, threshold zones, etc.) over time,
powering trend-line charts on the front-end.
"""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from typing import Optional

from ..database import get_db
from .. import models, schemas

router = APIRouter(prefix="/physiology", tags=["Physiology Logs"])


# ---------------------------------------------------------------------------
# CREATE
# ---------------------------------------------------------------------------
@router.post("/", response_model=schemas.PhysiologyLogRead, status_code=201)
def create_physiology_log(
    payload: schemas.PhysiologyLogCreate,
    db: Session = Depends(get_db),
):
    """Create a new physiology snapshot for a user on a given date."""
    db_log = models.PhysiologyLog(**payload.model_dump())
    db.add(db_log)
    db.commit()
    db.refresh(db_log)
    return db_log


# ---------------------------------------------------------------------------
# READ (list)
# ---------------------------------------------------------------------------
@router.get("/", response_model=list[schemas.PhysiologyLogRead])
def list_physiology_logs(
    pid: Optional[int] = Query(None, description="Filter by user ID"),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
):
    """Retrieve physiology logs, optionally filtered by user."""
    query = db.query(models.PhysiologyLog)
    if pid is not None:
        query = query.filter(models.PhysiologyLog.pid == pid)
    return query.order_by(models.PhysiologyLog.date.desc()).offset(skip).limit(limit).all()


# ---------------------------------------------------------------------------
# READ (single)
# ---------------------------------------------------------------------------
@router.get("/{log_id}", response_model=schemas.PhysiologyLogRead)
def get_physiology_log(log_id: int, db: Session = Depends(get_db)):
    """Retrieve a single physiology log by primary key."""
    log = db.query(models.PhysiologyLog).filter(models.PhysiologyLog.id == log_id).first()
    if not log:
        raise HTTPException(status_code=404, detail="PhysiologyLog not found")
    return log


# ---------------------------------------------------------------------------
# UPDATE (partial)
# ---------------------------------------------------------------------------
@router.put("/{log_id}", response_model=schemas.PhysiologyLogRead)
def update_physiology_log(
    log_id: int,
    payload: schemas.PhysiologyLogUpdate,
    db: Session = Depends(get_db),
):
    """Partially update an existing physiology log."""
    log = db.query(models.PhysiologyLog).filter(models.PhysiologyLog.id == log_id).first()
    if not log:
        raise HTTPException(status_code=404, detail="PhysiologyLog not found")

    update_data = payload.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(log, field, value)

    db.commit()
    db.refresh(log)
    return log


# ---------------------------------------------------------------------------
# DELETE
# ---------------------------------------------------------------------------
@router.delete("/{log_id}", status_code=204)
def delete_physiology_log(log_id: int, db: Session = Depends(get_db)):
    """Delete a physiology log. Returns 204 No Content on success."""
    log = db.query(models.PhysiologyLog).filter(models.PhysiologyLog.id == log_id).first()
    if not log:
        raise HTTPException(status_code=404, detail="PhysiologyLog not found")
    db.delete(log)
    db.commit()
    return None

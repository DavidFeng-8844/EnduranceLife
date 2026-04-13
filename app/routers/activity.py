"""
routers/activity.py — Full CRUD endpoints for the Activity table.

Design choices:
- All routes are grouped under the `/activities` prefix via an APIRouter
  with the tag "Activities" for clean OpenAPI documentation.
- Two creation paths:
    POST /  — JSON body (for programmatic clients)
    POST /upload — File upload (parse .fit directly from Swagger UI)
- The GET-list endpoint supports optional query filters (`pid`, `type`,
  `date_from`, `date_to`) and pagination (`skip`, `limit`).
- The PUT endpoint applies a partial-update pattern: only fields
  explicitly sent by the client (non-None) are written to the DB.
"""

import io
import json
import warnings
from datetime import date as date_type, datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, File, Form
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError
from typing import Optional

from ..database import get_db
from .. import models, schemas

router = APIRouter(prefix="/activities", tags=["Activities"])


# ===========================================================================
# .fit parsing helpers (extracted from scripts/import_fit.py so the API
# endpoint can reuse the same logic without importing the script module).
# ===========================================================================

SEMICIRCLE_TO_DEG = 180.0 / (2 ** 31)

SPORT_MAP = {
    "running": "Run",
    "cycling": "Ride",
    "training": "Run",
    "generic": "Other",
}


def _semicircles_to_degrees(semicircles):
    if semicircles is None:
        return None
    return semicircles * SEMICIRCLE_TO_DEG


def _speed_to_pace(speed_m_per_s):
    if not speed_m_per_s or speed_m_per_s <= 0:
        return None
    return int(round(1000.0 / speed_m_per_s))


def _parse_fit_bytes(file_bytes: bytes, filename: str) -> dict | None:
    """
    Parse .fit file content from raw bytes and return Activity-compatible dict.

    This mirrors the logic in scripts/import_fit.py but operates on in-memory
    bytes rather than a file path, enabling the upload endpoint to work without
    saving the file to disk.

    Returns None if no session message is found (not a workout file).
    """
    import fitdecode

    warnings.filterwarnings("ignore", module="fitdecode")
    session_data = None

    # Pass 1: session-level summary
    with fitdecode.FitReader(io.BytesIO(file_bytes)) as fit:
        for frame in fit:
            if frame.frame_type != fitdecode.FIT_FRAME_DATA:
                continue
            if frame.name != "session":
                continue

            sport_raw = frame.get_value("sport", fallback=None)
            sport_str = str(sport_raw) if sport_raw is not None else "generic"
            activity_type = SPORT_MAP.get(sport_str, "Other")

            start_time = frame.get_value("start_time", fallback=None)
            total_distance_m = frame.get_value("total_distance", fallback=0) or 0
            total_time_s = frame.get_value("total_timer_time", fallback=0) or 0
            total_ascent = frame.get_value("total_ascent", fallback=None)
            avg_hr = frame.get_value("avg_heart_rate", fallback=None)
            max_hr = frame.get_value("max_heart_rate", fallback=None)
            avg_speed = (
                frame.get_value("enhanced_avg_speed", fallback=None)
                or frame.get_value("avg_speed", fallback=None)
            )
            cadence_raw = frame.get_value("avg_running_cadence", fallback=None)
            avg_cadence = int(cadence_raw * 2) if cadence_raw else None
            temperature = frame.get_value("avg_temperature", fallback=None)
            training_load = frame.get_value("training_load", fallback=None)

            if isinstance(start_time, datetime):
                activity_date = start_time.date()
            else:
                activity_date = datetime.now(timezone.utc).date()
                start_time = datetime.now(timezone.utc)

            session_data = {
                "date": activity_date,
                "start_time": start_time,
                "distance_km": round(total_distance_m / 1000.0, 3),
                "duration_min": round(total_time_s / 60.0, 2),
                "type": activity_type,
                "altitude_gain": float(total_ascent) if total_ascent is not None else None,
                "avg_heart_rate": int(avg_hr) if avg_hr is not None else None,
                "max_heart_rate": int(max_hr) if max_hr is not None else None,
                "avg_pace_sec": _speed_to_pace(avg_speed),
                "avg_cadence": avg_cadence,
                "temperature": float(temperature) if temperature is not None else None,
                "training_load": float(training_load) if training_load is not None else None,
                "humidity": None,
                "air_pressure": None,
            }
            break

    if session_data is None:
        return None

    # Pass 2: record-level time-series
    hr_array = []
    pace_array = []
    first_lat = None
    first_lng = None

    with fitdecode.FitReader(io.BytesIO(file_bytes)) as fit:
        for frame in fit:
            if frame.frame_type != fitdecode.FIT_FRAME_DATA:
                continue
            if frame.name != "record":
                continue

            hr = frame.get_value("heart_rate", fallback=None)
            if hr is not None:
                hr_array.append(int(hr))

            speed = (
                frame.get_value("enhanced_speed", fallback=None)
                or frame.get_value("speed", fallback=None)
            )
            pace = _speed_to_pace(speed)
            if pace is not None:
                pace_array.append(pace)

            if first_lat is None:
                lat_raw = frame.get_value("position_lat", fallback=None)
                lng_raw = frame.get_value("position_long", fallback=None)
                if lat_raw is not None and lng_raw is not None:
                    first_lat = _semicircles_to_degrees(lat_raw)
                    first_lng = _semicircles_to_degrees(lng_raw)

    session_data["start_lat"] = round(first_lat, 6) if first_lat is not None else None
    session_data["start_lng"] = round(first_lng, 6) if first_lng is not None else None
    session_data["hr_array_json"] = json.dumps(hr_array) if hr_array else None
    session_data["pace_array_json"] = json.dumps(pace_array) if pace_array else None

    return session_data


# ---------------------------------------------------------------------------
# CREATE (JSON body — for programmatic clients)
# ---------------------------------------------------------------------------
@router.post("/", response_model=schemas.ActivityRead, status_code=201)
def create_activity(
    payload: schemas.ActivityCreate,
    db: Session = Depends(get_db),
):
    """
    Import a new activity record via JSON body.

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
# CREATE (file upload — parse .fit directly from Swagger UI)
# ---------------------------------------------------------------------------
@router.post(
    "/upload",
    response_model=schemas.ActivityRead,
    status_code=201,
    summary="Upload a .fit file and auto-parse it into an Activity record",
)
def upload_fit_file(
    file: UploadFile = File(..., description="A .fit file exported from Coros/Garmin"),
    pid: int = Form(1, description="User / person ID"),
    db: Session = Depends(get_db),
):
    """
    Upload a `.fit` file directly through Swagger UI or any HTTP client.

    The file is parsed in-memory using `fitdecode` and the raw bytes are
    stored in the database (`fit_file_blob`) for later re-parsing or download.
    Extracted fields include distance, duration, heart rate, pace, GPS
    coordinates, cadence, and time-series arrays.

    - Returns **201** with the created Activity on success.
    - Returns **409** if a file with the same name was already imported.
    - Returns **422** if the file contains no workout session data.
    """
    # Validate file extension
    if not file.filename or not file.filename.lower().endswith(".fit"):
        raise HTTPException(
            status_code=422,
            detail="Only .fit files are accepted. Please upload a valid .fit file.",
        )

    # Read file content into memory
    file_bytes = file.file.read()

    if len(file_bytes) == 0:
        raise HTTPException(status_code=422, detail="Uploaded file is empty.")

    # Parse the .fit content
    try:
        data = _parse_fit_bytes(file_bytes, file.filename)
    except Exception as e:
        raise HTTPException(
            status_code=422,
            detail=f"Failed to parse .fit file: {e}",
        )

    if data is None:
        raise HTTPException(
            status_code=422,
            detail=(
                "No workout session found in the uploaded file. "
                "This may be a device-settings, sleep, or non-activity file."
            ),
        )

    # Build and persist the Activity
    activity = models.Activity(
        pid=pid,
        source_file=file.filename,
        **data,
    )
    db.add(activity)
    try:
        db.commit()
        db.refresh(activity)
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail=(
                f"Activity with source_file '{file.filename}' already exists. "
                "Duplicate .fit file import is not allowed."
            ),
        )
    return activity


# ---------------------------------------------------------------------------
# READ (list with optional filters, date range, and pagination)
# ---------------------------------------------------------------------------
@router.get("/", response_model=list[schemas.ActivityRead])
def list_activities(
    pid: Optional[int] = Query(None, description="Filter by user ID"),
    type: Optional[str] = Query(None, description="Filter by activity type (Run / Ride)"),
    date_from: Optional[date_type] = Query(None, description="Start of date range (inclusive)"),
    date_to: Optional[date_type] = Query(None, description="End of date range (inclusive)"),
    skip: int = Query(0, ge=0, description="Number of records to skip"),
    limit: int = Query(50, ge=1, le=200, description="Max records to return"),
    db: Session = Depends(get_db),
):
    """
    Retrieve a paginated list of activities.

    Supports optional filtering by `pid`, `type`, and a date range
    (`date_from`, `date_to`) for efficient front-end chart windows.
    """
    query = db.query(models.Activity)
    if pid is not None:
        query = query.filter(models.Activity.pid == pid)
    if type is not None:
        query = query.filter(models.Activity.type == type)
    if date_from is not None:
        query = query.filter(models.Activity.date >= date_from)
    if date_to is not None:
        query = query.filter(models.Activity.date <= date_to)
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

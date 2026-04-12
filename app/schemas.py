"""
schemas.py — Pydantic V2 data-validation models.

Design choices:
- Every table has three Pydantic models:
    *Base   – shared fields used for both creation and reading.
    *Create – inherits Base; used as the request body for POST endpoints.
    *Read   – inherits Base; adds the `id` field and enables
              `from_attributes = True` so Pydantic can serialise
              SQLAlchemy ORM instances directly.
- Optional fields use `Optional[T] = None` to allow partial data submission,
  which is especially useful for Activity fields that may not exist in
  every .fit file (e.g. training_load is Coros-specific).
- `model_config = ConfigDict(from_attributes=True)` is the Pydantic V2
  equivalent of the V1 `class Config: orm_mode = True`.
"""

from datetime import date, datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


# ===========================================================================
# Activity schemas
# ===========================================================================

class ActivityBase(BaseModel):
    """Fields shared across creation and read responses."""

    pid: int = Field(..., description="User / person ID")
    source_file: str = Field(
        ..., description="Original .fit filename (used as dedup key)"
    )
    date: date
    start_time: datetime = Field(..., description="Activity start time in UTC")
    start_lat: Optional[float] = Field(None, description="Starting latitude")
    start_lng: Optional[float] = Field(None, description="Starting longitude")
    distance_km: float
    duration_min: float = Field(..., description="Total duration in minutes")
    type: str = Field(..., description="Activity type: 'Run' or 'Ride'")
    temperature: Optional[float] = None
    humidity: Optional[float] = None
    air_pressure: Optional[float] = None
    altitude_gain: Optional[float] = None
    avg_heart_rate: Optional[int] = None
    max_heart_rate: Optional[int] = None
    avg_pace_sec: Optional[int] = Field(None, description="Avg pace in sec/km")
    avg_cadence: Optional[int] = None
    training_load: Optional[float] = Field(
        None, description="Coros training load metric"
    )
    hr_array_json: Optional[str] = Field(
        None, description="JSON array string of HR time-series"
    )
    pace_array_json: Optional[str] = Field(
        None, description="JSON array string of pace time-series"
    )


class ActivityCreate(ActivityBase):
    """Request body for POST /activities."""

    pass


class ActivityUpdate(BaseModel):
    """
    Request body for PUT / PATCH /activities/{id}.

    All fields are optional so the client can send a partial update.
    """

    pid: Optional[int] = None
    source_file: Optional[str] = None
    date: Optional[date] = None
    start_time: Optional[datetime] = None
    start_lat: Optional[float] = None
    start_lng: Optional[float] = None
    distance_km: Optional[float] = None
    duration_min: Optional[float] = None
    type: Optional[str] = None
    temperature: Optional[float] = None
    humidity: Optional[float] = None
    air_pressure: Optional[float] = None
    altitude_gain: Optional[float] = None
    avg_heart_rate: Optional[int] = None
    max_heart_rate: Optional[int] = None
    avg_pace_sec: Optional[int] = None
    avg_cadence: Optional[int] = None
    training_load: Optional[float] = None
    hr_array_json: Optional[str] = None
    pace_array_json: Optional[str] = None


class ActivityRead(ActivityBase):
    """Response body returned by GET /activities endpoints."""

    id: int
    has_fit_file: bool = Field(
        False, description="True if the raw .fit file is stored and downloadable"
    )

    # Allow Pydantic to read attributes from SQLAlchemy model instances
    model_config = ConfigDict(from_attributes=True)

    @classmethod
    def model_validate(cls, obj, **kwargs):
        """Override to compute has_fit_file from the ORM object."""
        # Check if the ORM object has a non-null fit_file_blob
        if hasattr(obj, "fit_file_blob"):
            obj.__dict__["has_fit_file"] = obj.fit_file_blob is not None
        return super().model_validate(obj, **kwargs)


# ===========================================================================
# PhysiologyLog schemas
# ===========================================================================

class PhysiologyLogBase(BaseModel):
    pid: int
    date: date
    height_cm: Optional[float] = None
    weight_kg: Optional[float] = None
    running_fitness: Optional[float] = None
    vo2max: Optional[float] = None
    resting_heart_rate: Optional[int] = None
    threshold_hr_zones: Optional[str] = Field(
        None, description='JSON string, e.g. {"z1":"120-135"}'
    )
    threshold_pace_zones: Optional[str] = None


class PhysiologyLogCreate(PhysiologyLogBase):
    """Request body for POST /physiology."""

    pass


class PhysiologyLogUpdate(BaseModel):
    """Partial update schema — all fields optional."""

    pid: Optional[int] = None
    date: Optional[date] = None
    height_cm: Optional[float] = None
    weight_kg: Optional[float] = None
    running_fitness: Optional[float] = None
    vo2max: Optional[float] = None
    resting_heart_rate: Optional[int] = None
    threshold_hr_zones: Optional[str] = None
    threshold_pace_zones: Optional[str] = None


class PhysiologyLogRead(PhysiologyLogBase):
    id: int
    model_config = ConfigDict(from_attributes=True)


# ===========================================================================
# DailyMetric schemas
# ===========================================================================

class DailyMetricBase(BaseModel):
    pid: int
    date: date
    calories_in: Optional[int] = None
    protein_g: Optional[int] = None
    sleep_hours: Optional[float] = None
    fatigue_level: Optional[int] = Field(
        None, ge=1, le=10, description="Subjective fatigue 1-10"
    )
    recovery: Optional[float] = Field(
        None, ge=0, le=100, description="Recovery percentage"
    )
    deep_work_hours: Optional[float] = None
    stress_level: Optional[int] = Field(
        None, ge=1, le=10, description="Subjective stress 1-10"
    )


class DailyMetricCreate(DailyMetricBase):
    """Request body for POST /daily-metrics."""

    pass


class DailyMetricUpdate(BaseModel):
    """Partial update schema — all fields optional."""

    pid: Optional[int] = None
    date: Optional[date] = None
    calories_in: Optional[int] = None
    protein_g: Optional[int] = None
    sleep_hours: Optional[float] = None
    fatigue_level: Optional[int] = Field(None, ge=1, le=10)
    recovery: Optional[float] = Field(None, ge=0, le=100)
    deep_work_hours: Optional[float] = None
    stress_level: Optional[int] = Field(None, ge=1, le=10)


class DailyMetricRead(DailyMetricBase):
    id: int
    model_config = ConfigDict(from_attributes=True)

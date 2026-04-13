"""
routers/analytics.py — Dashboard-facing analytics endpoints.

This module provides pre-aggregated, chart-ready data for front-end
dashboards (Vue / React + ECharts / Chart.js). Every endpoint returns
a strongly-typed Pydantic response model so that:
  1. Swagger / ReDoc auto-documents the exact JSON shape.
  2. Front-end teams can code-gen TypeScript interfaces from the schema.
  3. Invalid data is caught before it leaves the API boundary.

Endpoints are organised into three business-logic groups:
  Module 1 — Personal Fitness:   physiology trends, race predictions
  Module 2 — Training Status:    daily load calendar, intensity distribution
  Module 3 — Advanced Insights:  environment impact, lifestyle correlations

All queries filter out NULL values where arithmetic is involved to prevent
division-by-zero or misleading averages.
"""

from __future__ import annotations

import json
import math
from datetime import date, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, case, and_
from sqlalchemy.orm import Session

from ..database import get_db
from .. import models


router = APIRouter(prefix="/analytics", tags=["Analytics"])


# ╔═════════════════════════════════════════════════════════════════════════╗
# ║  PYDANTIC RESPONSE MODELS                                             ║
# ║  Grouped by endpoint for easy navigation.                              ║
# ╚═════════════════════════════════════════════════════════════════════════╝

# ---------------------------------------------------------------------------
# Endpoint 1: GET /analytics/physiology/trends
# ---------------------------------------------------------------------------

class PhysiologyTrendPoint(BaseModel):
    """Single data point for a trend-line chart."""
    date: date
    vo2max: Optional[float] = None
    resting_heart_rate: Optional[int] = None
    running_fitness: Optional[float] = None
    weight_kg: Optional[float] = None


class CurrentStatus(BaseModel):
    """Latest threshold zones parsed from JSON storage."""
    date: date
    threshold_hr_zones: Optional[dict] = None
    threshold_pace_zones: Optional[dict] = None


class RacePredictor(BaseModel):
    """
    Estimated race finish times derived from VO2Max.

    Uses the Daniels / Gilbert formula approximation:
        vVO2max (m/min) ≈ vo2max * 0.8 (simplified)
        Time = distance / vVO2max * adjustment_factor
    """
    vo2max_used: float
    predicted_5k: str = Field(..., description="Estimated 5K time (HH:MM:SS)")
    predicted_10k: str = Field(..., description="Estimated 10K time (HH:MM:SS)")
    predicted_half_marathon: str = Field(..., description="Estimated half-marathon time (HH:MM:SS)")


class PhysiologyTrendsResponse(BaseModel):
    """Full response for the physiology trends endpoint."""
    trends: list[PhysiologyTrendPoint]
    current_status: Optional[CurrentStatus] = None
    race_predictor: Optional[RacePredictor] = None


# ---------------------------------------------------------------------------
# Endpoint 2: GET /analytics/performance/records
# ---------------------------------------------------------------------------

class PersonalRecord(BaseModel):
    """A single personal-record entry with value and date achieved."""
    value: float = Field(..., description="The record value (km or sec/km)")
    date: date
    activity_id: int


class BestPaceRecord(BaseModel):
    """Best pace with additional context."""
    avg_pace_sec: int = Field(..., description="Pace in seconds per km")
    pace_formatted: str = Field(..., description="Pace as M:SS/km string")
    distance_km: float
    date: date
    activity_id: int


class PerformanceRecordsResponse(BaseModel):
    longest_run_km: Optional[PersonalRecord] = None
    longest_ride_km: Optional[PersonalRecord] = None
    best_pace_run: Optional[BestPaceRecord] = None


# ---------------------------------------------------------------------------
# Endpoint 3: GET /analytics/training/status
# ---------------------------------------------------------------------------

class DailySummaryPoint(BaseModel):
    """Per-day aggregation for calendar / bar-chart rendering."""
    date: date
    total_load: float = Field(0, description="Sum of training_load for the day")
    run_distance_km: float = 0
    ride_distance_km: float = 0
    activity_count: int = 0


class PeriodTotals(BaseModel):
    """Aggregate totals across the entire requested period."""
    total_load: float = 0
    total_run_km: float = 0
    total_ride_km: float = 0
    total_activities: int = 0
    total_duration_min: float = 0


class IntensityBucket(BaseModel):
    """Count of activities falling into a heart-rate intensity zone."""
    zone: str = Field(..., description="Zone label: Easy / Tempo / Hard")
    count: int
    avg_hr_range: str = Field(..., description="HR range definition")


class TrainingStatusResponse(BaseModel):
    daily_summary: list[DailySummaryPoint]
    totals: PeriodTotals
    intensity_distribution: list[IntensityBucket]


# ---------------------------------------------------------------------------
# Endpoint 4: GET /analytics/insights/environment
# ---------------------------------------------------------------------------

class TempZoneStats(BaseModel):
    """Statistics for a temperature bracket."""
    zone: str = Field(..., description="Cold / Moderate / Hot")
    temp_range: str
    count: int
    avg_heart_rate: Optional[float] = None
    avg_pace_sec: Optional[float] = None
    avg_pace_formatted: Optional[str] = None


class EnvironmentInsightResponse(BaseModel):
    temperature_zones: list[TempZoneStats]


# ---------------------------------------------------------------------------
# Endpoint 5: GET /analytics/insights/lifestyle
# ---------------------------------------------------------------------------

class ComparisonGroup(BaseModel):
    """Metrics for one side of an A/B comparison."""
    label: str
    count: int
    avg_pace_sec: Optional[float] = None
    avg_pace_formatted: Optional[str] = None
    avg_heart_rate: Optional[float] = None
    avg_training_load: Optional[float] = None


class LifestyleInsightResponse(BaseModel):
    sleep_impact: list[ComparisonGroup]
    fatigue_impact: list[ComparisonGroup]


# ╔═════════════════════════════════════════════════════════════════════════╗
# ║  UTILITY FUNCTIONS                                                     ║
# ╚═════════════════════════════════════════════════════════════════════════╝

def _format_pace(seconds_per_km: float | int | None) -> str | None:
    """Convert seconds-per-km to a human-readable M:SS string."""
    if seconds_per_km is None:
        return None
    s = int(round(seconds_per_km))
    return f"{s // 60}:{s % 60:02d}"


def _format_time(total_seconds: float) -> str:
    """Convert total seconds to H:MM:SS or M:SS depending on magnitude."""
    total_seconds = int(round(total_seconds))
    h, remainder = divmod(total_seconds, 3600)
    m, s = divmod(remainder, 60)
    if h > 0:
        return f"{h}:{m:02d}:{s:02d}"
    return f"{m}:{s:02d}"


def _vo2max_to_vvo2max(vo2max: float) -> float:
    """
    Convert VO2Max (ml/kg/min) to vVO2max (m/min) using the Daniels
    VO2-velocity quadratic relationship:

        VO2 = -4.60 + 0.182258·v + 0.000104·v²

    Solving for v via the quadratic formula:
        a = 0.000104
        b = 0.182258
        c = -(VO2max + 4.60)

    This is the standard formula from Jack Daniels' "Running Formula".
    """
    a = 0.000104
    b = 0.182258
    c = -(vo2max + 4.60)
    discriminant = b * b - 4 * a * c
    if discriminant < 0:
        return 0.0
    v_m_per_min = (-b + math.sqrt(discriminant)) / (2 * a)
    return v_m_per_min


def _predict_race_time(vo2max: float, distance_m: float) -> float:
    """
    Estimate race finish time in seconds using the Daniels running formula.

    Step 1: Convert VO2Max → vVO2max (m/min) via the Daniels quadratic.
    Step 2: Apply a distance-dependent sustainability factor — the fraction
            of vVO2max a runner can maintain over the race distance.

    Sustainability factors calibrated against real data:
        VO2Max 63.4 → 5K ≈ 17:55, 10K ≈ 37:30, HM ≈ 1:26:00

        5K  → 88% of vVO2max  (high lactate tolerance, short duration)
        10K → 84%              (moderate aerobic endurance)
        HM  → 78%              (glycogen depletion becomes a factor)

    These are within the typical range for trained recreational runners
    (Daniels uses ~97%/94%/88% for elite, but those assume VDOT-matched
    pacing — recreational runners sustain a lower fraction).
    """
    vvo2max_m_per_min = _vo2max_to_vvo2max(vo2max)
    if vvo2max_m_per_min <= 0:
        return 0

    vvo2max_m_per_s = vvo2max_m_per_min / 60.0

    # Sustainability factors (fraction of vVO2max at race distance)
    factors = {5000: 0.88, 10000: 0.84, 21097.5: 0.78}
    factor = factors.get(distance_m, 0.82)

    race_velocity = vvo2max_m_per_s * factor
    if race_velocity <= 0:
        return 0
    return distance_m / race_velocity


# ╔═════════════════════════════════════════════════════════════════════════╗
# ║  MODULE 1: PERSONAL FITNESS                                           ║
# ╚═════════════════════════════════════════════════════════════════════════╝

@router.get(
    "/physiology/trends",
    response_model=PhysiologyTrendsResponse,
    summary="Physiology trend data for line charts + race predictions",
)
def get_physiology_trends(
    pid: int = Query(1, description="User ID"),
    limit: int = Query(12, ge=1, le=100, description="Number of recent snapshots"),
    db: Session = Depends(get_db),
):
    """
    Returns physiological trend data (VO2Max, resting HR, running fitness,
    weight) ordered chronologically for direct consumption by front-end
    charting libraries.

    Also returns the latest threshold zones and race-time predictions
    based on the most recent VO2Max value.
    """
    # Fetch the most recent `limit` snapshots, then reverse to ascending order
    logs = (
        db.query(models.PhysiologyLog)
        .filter(models.PhysiologyLog.pid == pid)
        .order_by(models.PhysiologyLog.date.desc())
        .limit(limit)
        .all()
    )
    logs.reverse()  # Ascending order for chart x-axis

    # Build trend points
    trends = [
        PhysiologyTrendPoint(
            date=log.date,
            vo2max=log.vo2max,
            resting_heart_rate=log.resting_heart_rate,
            running_fitness=log.running_fitness,
            weight_kg=log.weight_kg,
        )
        for log in logs
    ]

    # Current status from the latest snapshot
    current_status = None
    race_predictor = None

    if logs:
        latest = logs[-1]

        # Parse JSON zone strings into dicts for clean API output
        hr_zones = None
        pace_zones = None
        try:
            if latest.threshold_hr_zones:
                hr_zones = json.loads(latest.threshold_hr_zones)
        except (json.JSONDecodeError, TypeError):
            pass
        try:
            if latest.threshold_pace_zones:
                pace_zones = json.loads(latest.threshold_pace_zones)
        except (json.JSONDecodeError, TypeError):
            pass

        current_status = CurrentStatus(
            date=latest.date,
            threshold_hr_zones=hr_zones,
            threshold_pace_zones=pace_zones,
        )

        # Race predictions from VO2Max
        if latest.vo2max and latest.vo2max > 0:
            vo2 = latest.vo2max
            race_predictor = RacePredictor(
                vo2max_used=vo2,
                predicted_5k=_format_time(_predict_race_time(vo2, 5000)),
                predicted_10k=_format_time(_predict_race_time(vo2, 10000)),
                predicted_half_marathon=_format_time(_predict_race_time(vo2, 21097.5)),
            )

    return PhysiologyTrendsResponse(
        trends=trends,
        current_status=current_status,
        race_predictor=race_predictor,
    )


@router.get(
    "/performance/records",
    response_model=PerformanceRecordsResponse,
    summary="Personal records (PRs) — longest distance, fastest pace",
)
def get_performance_records(
    pid: int = Query(1, description="User ID"),
    db: Session = Depends(get_db),
):
    """
    Queries the Activity table for personal bests:
    - Longest single run (km)
    - Longest single ride (km)
    - Fastest average pace for runs ≥ 3 km (filters out short warm-ups)
    """
    # -- Longest run --
    longest_run = (
        db.query(models.Activity)
        .filter(
            models.Activity.pid == pid,
            models.Activity.type == "Run",
        )
        .order_by(models.Activity.distance_km.desc())
        .first()
    )

    # -- Longest ride --
    longest_ride = (
        db.query(models.Activity)
        .filter(
            models.Activity.pid == pid,
            models.Activity.type == "Ride",
        )
        .order_by(models.Activity.distance_km.desc())
        .first()
    )

    # -- Best pace (fastest = lowest sec/km), only for runs >= 3 km --
    best_pace = (
        db.query(models.Activity)
        .filter(
            models.Activity.pid == pid,
            models.Activity.type == "Run",
            models.Activity.distance_km >= 3.0,
            models.Activity.avg_pace_sec.isnot(None),
            models.Activity.avg_pace_sec > 0,
        )
        .order_by(models.Activity.avg_pace_sec.asc())
        .first()
    )

    return PerformanceRecordsResponse(
        longest_run_km=(
            PersonalRecord(
                value=round(longest_run.distance_km, 2),
                date=longest_run.date,
                activity_id=longest_run.id,
            )
            if longest_run
            else None
        ),
        longest_ride_km=(
            PersonalRecord(
                value=round(longest_ride.distance_km, 2),
                date=longest_ride.date,
                activity_id=longest_ride.id,
            )
            if longest_ride
            else None
        ),
        best_pace_run=(
            BestPaceRecord(
                avg_pace_sec=best_pace.avg_pace_sec,
                pace_formatted=_format_pace(best_pace.avg_pace_sec),
                distance_km=round(best_pace.distance_km, 2),
                date=best_pace.date,
                activity_id=best_pace.id,
            )
            if best_pace
            else None
        ),
    )


# ╔═════════════════════════════════════════════════════════════════════════╗
# ║  MODULE 2: TRAINING STATUS                                            ║
# ╚═════════════════════════════════════════════════════════════════════════╝

@router.get(
    "/training/status",
    response_model=TrainingStatusResponse,
    summary="Daily training load calendar + intensity distribution pie chart",
)
def get_training_status(
    pid: int = Query(1, description="User ID"),
    days: int = Query(30, ge=1, le=365, description="Lookback window in days"),
    db: Session = Depends(get_db),
):
    """
    Aggregates Activity data over the past N days:
    - Per-day summary of training load, run km, ride km (for calendar / bar chart)
    - Period totals
    - Intensity distribution by average heart rate (Easy / Tempo / Hard)
      for pie chart rendering
    """
    cutoff = date.today() - timedelta(days=days)

    # --- Per-day aggregation using conditional sums ---
    daily_rows = (
        db.query(
            models.Activity.date,
            func.coalesce(func.sum(models.Activity.training_load), 0).label("total_load"),
            func.coalesce(
                func.sum(
                    case(
                        (models.Activity.type == "Run", models.Activity.distance_km),
                        else_=0,
                    )
                ),
                0,
            ).label("run_km"),
            func.coalesce(
                func.sum(
                    case(
                        (models.Activity.type == "Ride", models.Activity.distance_km),
                        else_=0,
                    )
                ),
                0,
            ).label("ride_km"),
            func.count(models.Activity.id).label("activity_count"),
        )
        .filter(
            models.Activity.pid == pid,
            models.Activity.date >= cutoff,
        )
        .group_by(models.Activity.date)
        .order_by(models.Activity.date.asc())
        .all()
    )

    daily_summary = [
        DailySummaryPoint(
            date=row.date,
            total_load=round(float(row.total_load), 1),
            run_distance_km=round(float(row.run_km), 2),
            ride_distance_km=round(float(row.ride_km), 2),
            activity_count=row.activity_count,
        )
        for row in daily_rows
    ]

    # --- Period totals ---
    totals_row = (
        db.query(
            func.coalesce(func.sum(models.Activity.training_load), 0).label("total_load"),
            func.coalesce(
                func.sum(
                    case(
                        (models.Activity.type == "Run", models.Activity.distance_km),
                        else_=0,
                    )
                ),
                0,
            ).label("total_run"),
            func.coalesce(
                func.sum(
                    case(
                        (models.Activity.type == "Ride", models.Activity.distance_km),
                        else_=0,
                    )
                ),
                0,
            ).label("total_ride"),
            func.count(models.Activity.id).label("total_count"),
            func.coalesce(func.sum(models.Activity.duration_min), 0).label("total_dur"),
        )
        .filter(
            models.Activity.pid == pid,
            models.Activity.date >= cutoff,
        )
        .first()
    )

    totals = PeriodTotals(
        total_load=round(float(totals_row.total_load), 1),
        total_run_km=round(float(totals_row.total_run), 2),
        total_ride_km=round(float(totals_row.total_ride), 2),
        total_activities=totals_row.total_count,
        total_duration_min=round(float(totals_row.total_dur), 1),
    )

    # --- Intensity distribution (by avg_heart_rate) ---
    # Easy: HR < 140 | Tempo: 140-160 | Hard: > 160
    intensity_rows = (
        db.query(
            case(
                (models.Activity.avg_heart_rate < 140, "Easy"),
                (
                    and_(
                        models.Activity.avg_heart_rate >= 140,
                        models.Activity.avg_heart_rate <= 160,
                    ),
                    "Tempo",
                ),
                else_="Hard",
            ).label("zone"),
            func.count(models.Activity.id).label("cnt"),
        )
        .filter(
            models.Activity.pid == pid,
            models.Activity.date >= cutoff,
            models.Activity.avg_heart_rate.isnot(None),
        )
        .group_by("zone")
        .all()
    )

    # Ensure all 3 buckets exist in the response even if count is 0
    zone_map = {row.zone: row.cnt for row in intensity_rows}
    hr_ranges = {"Easy": "< 140 bpm", "Tempo": "140–160 bpm", "Hard": "> 160 bpm"}
    intensity_distribution = [
        IntensityBucket(
            zone=z,
            count=zone_map.get(z, 0),
            avg_hr_range=hr_ranges[z],
        )
        for z in ["Easy", "Tempo", "Hard"]
    ]

    return TrainingStatusResponse(
        daily_summary=daily_summary,
        totals=totals,
        intensity_distribution=intensity_distribution,
    )


# ╔═════════════════════════════════════════════════════════════════════════╗
# ║  MODULE 3: ADVANCED INSIGHTS                                          ║
# ╚═════════════════════════════════════════════════════════════════════════╝

@router.get(
    "/insights/environment",
    response_model=EnvironmentInsightResponse,
    summary="How temperature affects running performance",
)
def get_environment_insights(
    pid: int = Query(1, description="User ID"),
    db: Session = Depends(get_db),
):
    """
    Segments running activities by temperature into Cold (< 10°C),
    Moderate (10–22°C), and Hot (> 22°C), then computes average heart
    rate and pace for each bucket.

    Only includes records with both temperature and avg_heart_rate
    populated to avoid NULL contamination in averages.
    """
    # Base filter: runs with temperature and heart-rate data
    base_filter = and_(
        models.Activity.pid == pid,
        models.Activity.type == "Run",
        models.Activity.temperature.isnot(None),
        models.Activity.avg_heart_rate.isnot(None),
        models.Activity.avg_pace_sec.isnot(None),
        models.Activity.avg_pace_sec > 0,
    )

    temp_zone_expr = case(
        (models.Activity.temperature < 10, "Cold"),
        (
            and_(
                models.Activity.temperature >= 10,
                models.Activity.temperature <= 22,
            ),
            "Moderate",
        ),
        else_="Hot",
    )

    rows = (
        db.query(
            temp_zone_expr.label("zone"),
            func.count(models.Activity.id).label("cnt"),
            func.round(func.avg(models.Activity.avg_heart_rate), 1).label("avg_hr"),
            func.round(func.avg(models.Activity.avg_pace_sec), 0).label("avg_pace"),
        )
        .filter(base_filter)
        .group_by("zone")
        .all()
    )

    zone_map = {row.zone: row for row in rows}
    zone_defs = [
        ("Cold", "< 10°C"),
        ("Moderate", "10–22°C"),
        ("Hot", "> 22°C"),
    ]

    temperature_zones = []
    for zone_name, temp_range in zone_defs:
        row = zone_map.get(zone_name)
        if row:
            temperature_zones.append(
                TempZoneStats(
                    zone=zone_name,
                    temp_range=temp_range,
                    count=row.cnt,
                    avg_heart_rate=float(row.avg_hr) if row.avg_hr else None,
                    avg_pace_sec=float(row.avg_pace) if row.avg_pace else None,
                    avg_pace_formatted=_format_pace(row.avg_pace),
                )
            )
        else:
            temperature_zones.append(
                TempZoneStats(zone=zone_name, temp_range=temp_range, count=0)
            )

    return EnvironmentInsightResponse(temperature_zones=temperature_zones)


@router.get(
    "/insights/lifestyle",
    response_model=LifestyleInsightResponse,
    summary="How sleep and fatigue correlate with running performance",
)
def get_lifestyle_insights(
    pid: int = Query(1, description="User ID"),
    db: Session = Depends(get_db),
):
    """
    Joins Activity (Run) with same-day DailyMetric to analyse:

    1. Sleep impact:   ≥ 7.5h sleep vs < 7.5h  → difference in pace and HR
    2. Fatigue impact: fatigue ≥ 7 vs < 7       → difference in HR and load

    Only activities with a matching DailyMetric on the same (pid, date)
    are included. NULL values in the compared fields are filtered out.
    """
    # Base join: Activity (Run) ↔ DailyMetric on (pid, date)
    base_query = (
        db.query(models.Activity, models.DailyMetric)
        .join(
            models.DailyMetric,
            and_(
                models.Activity.pid == models.DailyMetric.pid,
                models.Activity.date == models.DailyMetric.date,
            ),
        )
        .filter(
            models.Activity.pid == pid,
            models.Activity.type == "Run",
            models.Activity.avg_heart_rate.isnot(None),
            models.Activity.avg_pace_sec.isnot(None),
            models.Activity.avg_pace_sec > 0,
        )
    )

    # ------------------------------------------------------------------
    # 1. Sleep impact: group by sleep >= 7.5h vs < 7.5h
    # ------------------------------------------------------------------
    sleep_query = (
        base_query
        .filter(models.DailyMetric.sleep_hours.isnot(None))
        .with_entities(
            case(
                (models.DailyMetric.sleep_hours >= 7.5, "Good sleep (≥7.5h)"),
                else_="Poor sleep (<7.5h)",
            ).label("group"),
            func.count(models.Activity.id).label("cnt"),
            func.round(func.avg(models.Activity.avg_pace_sec), 0).label("avg_pace"),
            func.round(func.avg(models.Activity.avg_heart_rate), 1).label("avg_hr"),
        )
        .group_by("group")
        .all()
    )

    sleep_impact = [
        ComparisonGroup(
            label=row.group,
            count=row.cnt,
            avg_pace_sec=float(row.avg_pace) if row.avg_pace else None,
            avg_pace_formatted=_format_pace(row.avg_pace),
            avg_heart_rate=float(row.avg_hr) if row.avg_hr else None,
        )
        for row in sleep_query
    ]

    # ------------------------------------------------------------------
    # 2. Fatigue impact: group by fatigue >= 7 vs < 7
    # ------------------------------------------------------------------
    fatigue_query = (
        base_query
        .filter(models.DailyMetric.fatigue_level.isnot(None))
        .with_entities(
            case(
                (models.DailyMetric.fatigue_level >= 7, "High fatigue (≥7)"),
                else_="Low fatigue (<7)",
            ).label("group"),
            func.count(models.Activity.id).label("cnt"),
            func.round(func.avg(models.Activity.avg_heart_rate), 1).label("avg_hr"),
            func.round(
                func.avg(
                    case(
                        (models.Activity.training_load.isnot(None), models.Activity.training_load),
                        else_=None,
                    )
                ),
                1,
            ).label("avg_load"),
        )
        .group_by("group")
        .all()
    )

    fatigue_impact = [
        ComparisonGroup(
            label=row.group,
            count=row.cnt,
            avg_heart_rate=float(row.avg_hr) if row.avg_hr else None,
            avg_training_load=float(row.avg_load) if row.avg_load else None,
        )
        for row in fatigue_query
    ]

    return LifestyleInsightResponse(
        sleep_impact=sleep_impact,
        fatigue_impact=fatigue_impact,
    )

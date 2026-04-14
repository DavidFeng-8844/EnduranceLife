"""
models.py — SQLAlchemy ORM table definitions.

Design choices:
- Three tables mirror the domain: Activity (workout data from .fit files),
  PhysiologyLog (body-state snapshots), and DailyMetric (nutrition/recovery).
- `source_file` on Activity has a unique constraint so the same .fit file
  cannot be imported twice.
- `DailyMetric` enforces a composite unique constraint on (pid, date) at the
  DB level, guaranteeing one record per user per day regardless of
  application-level checks.
- JSON time-series data (heart-rate arrays, pace arrays, HR-zone configs)
  are stored as plain Text columns containing JSON strings. This avoids
  the need for a JSON column type (not natively supported by SQLite) while
  remaining easy to parse in Python via `json.loads()`.
"""

from sqlalchemy import (
    Column,
    Integer,
    Float,
    String,
    Text,
    Date,
    DateTime,
    Boolean,
    UniqueConstraint,
)

from .database import Base


class User(Base):
    """
    Registered API user for authentication.
    Passwords are stored as bcrypt hashes — never plaintext.
    """

    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, nullable=False, unique=True, index=True)
    hashed_password = Column(String, nullable=False)
    is_active = Column(Boolean, default=True, comment="Soft-delete flag")


class Activity(Base):
    """
    Represents a single workout session parsed from a .fit file.

    Key fields:
    - start_lat / start_lng: capture the GPS coordinates at the start of the
      activity so we can later call an external weather API to backfill
      temperature / humidity / air_pressure.
    - hr_array_json / pace_array_json: store the full time-series data as
      JSON array strings (e.g. "[72, 75, 80, ...]") for front-end charting.
    - training_load: a Coros-specific metric; nullable for non-Coros devices.
    """

    __tablename__ = "activities"

    id = Column(Integer, primary_key=True, index=True)
    pid = Column(Integer, nullable=False, index=True, comment="User / person ID")
    source_file = Column(
        String,
        nullable=False,
        comment="Original .fit filename to prevent duplicate imports",
    )
    date = Column(Date, nullable=False)
    start_time = Column(DateTime, nullable=False, comment="Activity start in UTC")
    start_lat = Column(Float, nullable=True, comment="Starting latitude for weather lookup")
    start_lng = Column(Float, nullable=True, comment="Starting longitude for weather lookup")
    distance_km = Column(Float, nullable=False)
    duration_min = Column(Float, nullable=False, comment="Total duration in minutes")
    type = Column(String, nullable=False, comment="Activity type: Run or Ride")
    temperature = Column(Float, nullable=True, comment="°C — from weather API or watch sensor")
    humidity = Column(Float, nullable=True, comment="Relative humidity %")
    air_pressure = Column(Float, nullable=True, comment="hPa")
    altitude_gain = Column(Float, nullable=True, comment="Cumulative elevation gain in meters")
    avg_heart_rate = Column(Integer, nullable=True)
    max_heart_rate = Column(Integer, nullable=True)
    avg_pace_sec = Column(Integer, nullable=True, comment="Average pace in seconds per km")
    avg_cadence = Column(Integer, nullable=True)
    training_load = Column(Float, nullable=True, comment="Coros training load metric")
    hr_array_json = Column(Text, nullable=True, comment="JSON array of HR time-series")
    pace_array_json = Column(Text, nullable=True, comment="JSON array of pace time-series")

    # Prevent the same .fit file from being imported more than once
    __table_args__ = (
        UniqueConstraint("source_file", name="uq_activity_source_file"),
    )


class PhysiologyLog(Base):
    """
    Tracks changes in a user's physiological metrics over time.
    Intended for front-end line-chart visualisation of fitness trends.

    - threshold_hr_zones / threshold_pace_zones are stored as JSON strings,
      e.g. '{"z1": "120-135", "z2": "136-150", ...}'.
    """

    __tablename__ = "physiology_logs"

    id = Column(Integer, primary_key=True, index=True)
    pid = Column(Integer, nullable=False, index=True, comment="User / person ID")
    date = Column(Date, nullable=False, comment="Date of this snapshot")
    height_cm = Column(Float, nullable=True)
    weight_kg = Column(Float, nullable=True)
    running_fitness = Column(Float, nullable=True)
    vo2max = Column(Float, nullable=True)
    resting_heart_rate = Column(Integer, nullable=True)
    threshold_hr_zones = Column(
        Text,
        nullable=True,
        comment='JSON string, e.g. {"z1":"120-135","z2":"136-150"}',
    )
    threshold_pace_zones = Column(
        Text,
        nullable=True,
        comment="JSON string of pace zone definitions",
    )

    # One snapshot per user per date — prevents duplicate seeding runs
    __table_args__ = (
        UniqueConstraint("pid", "date", name="uq_physiology_log_pid_date"),
    )


class DailyMetric(Base):
    """
    Captures daily nutrition, sleep, and subjective wellness data.
    Cross-referenced with Activity records to analyse how lifestyle
    factors correlate with athletic performance.

    The composite unique constraint on (pid, date) is the most critical
    integrity rule in this table — it ensures at most one row per user
    per day, which simplifies aggregation queries and prevents accidental
    duplicate entries.
    """

    __tablename__ = "daily_metrics"

    id = Column(Integer, primary_key=True, index=True)
    pid = Column(Integer, nullable=False, index=True, comment="User / person ID")
    date = Column(Date, nullable=False)
    calories_in = Column(Integer, nullable=True)
    protein_g = Column(Integer, nullable=True)
    sleep_hours = Column(Float, nullable=True)
    fatigue_level = Column(Integer, nullable=True, comment="Subjective 1-10 scale")
    recovery = Column(Float, nullable=True, comment="Recovery percentage 0-100")
    deep_work_hours = Column(Float, nullable=True)
    stress_level = Column(Integer, nullable=True, comment="Subjective 1-10 scale")

    # CRITICAL: one record per user per day
    __table_args__ = (
        UniqueConstraint("pid", "date", name="uq_daily_metric_pid_date"),
    )

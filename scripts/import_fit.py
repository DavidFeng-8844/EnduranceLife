"""
scripts/import_fit.py — Batch-import Coros .fit files into the Activity table.

This script uses `fitdecode` (NOT `fitparse`) because Coros watches produce
FIT files with non-standard field sizing (e.g. uint32 packed into 1 byte)
that cause fitparse to crash with FitParseError. `fitdecode` handles these
gracefully, emitting warnings instead of exceptions.

Usage (from the project root):
    python -m scripts.import_fit               # default pid=1
    python -m scripts.import_fit --pid 42      # specify user ID
    python -m scripts.import_fit --dir data/coros --pid 1

Design choices:
- Defensive parsing: every field extraction uses `frame.get_value(name,
  fallback=None)` so a missing or malformed field never crashes the script.
- Files that have no `session` message (e.g. device settings, sleep logs)
  are silently skipped — they are not workout data.
- Duplicate imports are handled at the DB level via the `source_file`
  unique constraint; the script catches IntegrityError and moves on.
- Time-series arrays (HR, pace) are built from `record` messages and
  stored as JSON strings, exactly as the Activity model expects.
"""

import json
import os
import sys
import warnings
import argparse
from datetime import datetime, timezone

import fitdecode
from sqlalchemy.exc import IntegrityError

# ---------------------------------------------------------------------------
# Ensure the project root is on sys.path so we can import `app.*`
# ---------------------------------------------------------------------------
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from app.database import SessionLocal, engine, Base  # noqa: E402
from app.models import Activity  # noqa: E402

# Suppress fitdecode warnings about non-standard field sizes (common in
# Coros files). The data is still parsed correctly despite these warnings.
warnings.filterwarnings("ignore", module="fitdecode")


# ===========================================================================
# Constants
# ===========================================================================

# Semicircles-to-degrees conversion factor.
# The FIT protocol stores lat/lng as signed 32-bit integers where
# 2^31 semicircles = 180 degrees.
SEMICIRCLE_TO_DEG = 180.0 / (2 ** 31)

# Map FIT sport enum strings to our simplified activity types.
# Coros uses these values in the `sport` field of session messages.
SPORT_MAP = {
    "running":  "Run",
    "cycling":  "Ride",
    "training": "Run",   # Coros tags treadmill / interval sessions as 'training'
    "generic":  "Other",
}

# Default data directory relative to project root
DEFAULT_DATA_DIR = os.path.join("data", "coros")


# ===========================================================================
# Helper functions
# ===========================================================================

def semicircles_to_degrees(semicircles):
    """
    Convert FIT semicircle coordinates to standard decimal degrees.

    FIT protocol encodes positions as signed 32-bit integers where the
    full circle (360°) = 2^32 semicircles. This function converts to the
    familiar [-180, 180] / [-90, 90] range used by mapping APIs.
    """
    if semicircles is None:
        return None
    return semicircles * SEMICIRCLE_TO_DEG


def speed_to_pace(speed_m_per_s):
    """
    Convert speed (m/s) to pace (seconds per kilometre).

    Returns an integer (rounded) or None if speed is zero / missing.
    A speed of 0 would result in division by zero, so we guard against it.
    """
    if not speed_m_per_s or speed_m_per_s <= 0:
        return None
    # pace = 1000m / speed_m_per_s  →  seconds per km
    return int(round(1000.0 / speed_m_per_s))


def parse_fit_file(filepath):
    """
    Parse a single .fit file and return a dict of Activity-compatible fields.

    Returns None if the file contains no session message (e.g. device config,
    sleep data, or other non-workout file types exported by Coros).

    The function is split into two passes over the file:
      1. Session pass — extract summary metrics from the `session` message.
      2. Record pass — iterate `record` messages to build HR and pace arrays.

    This two-pass approach keeps memory usage low and avoids loading the
    entire file into memory at once.
    """
    session_data = None

    # -----------------------------------------------------------------------
    # Pass 1: Extract session-level summary data
    # -----------------------------------------------------------------------
    with fitdecode.FitReader(filepath) as fit:
        for frame in fit:
            if frame.frame_type != fitdecode.FIT_FRAME_DATA:
                continue
            if frame.name != "session":
                continue

            # We found the session message — extract all fields defensively.
            # `get_value` returns the fallback (None) when a field is absent,
            # which is common with Coros's custom / proprietary fields.
            sport_raw = frame.get_value("sport", fallback=None)
            sport_str = str(sport_raw) if sport_raw is not None else "generic"
            activity_type = SPORT_MAP.get(sport_str, "Other")

            start_time = frame.get_value("start_time", fallback=None)
            total_distance_m = frame.get_value("total_distance", fallback=0) or 0
            total_time_s = frame.get_value("total_timer_time", fallback=0) or 0
            total_ascent = frame.get_value("total_ascent", fallback=None)

            avg_hr = frame.get_value("avg_heart_rate", fallback=None)
            max_hr = frame.get_value("max_heart_rate", fallback=None)

            # Coros uses `enhanced_avg_speed` (m/s); fall back to `avg_speed`
            avg_speed = (
                frame.get_value("enhanced_avg_speed", fallback=None)
                or frame.get_value("avg_speed", fallback=None)
            )

            # Cadence: Coros reports running cadence in strides/min;
            # multiply by 2 to get steps/min (industry standard for running).
            cadence_raw = frame.get_value("avg_running_cadence", fallback=None)
            avg_cadence = int(cadence_raw * 2) if cadence_raw else None

            # Temperature may come from the watch sensor or be absent
            temperature = frame.get_value("avg_temperature", fallback=None)

            # Training load is a Coros-proprietary field — may not exist
            training_load = frame.get_value("training_load", fallback=None)

            # Derive the activity date from start_time
            if isinstance(start_time, datetime):
                activity_date = start_time.date()
            else:
                # Fallback: use file modification time
                activity_date = datetime.fromtimestamp(
                    os.path.getmtime(filepath), tz=timezone.utc
                ).date()
                start_time = datetime.fromtimestamp(
                    os.path.getmtime(filepath), tz=timezone.utc
                )

            session_data = {
                "date": activity_date,
                "start_time": start_time,
                "distance_km": round(total_distance_m / 1000.0, 3),
                "duration_min": round(total_time_s / 60.0, 2),
                "type": activity_type,
                "altitude_gain": float(total_ascent) if total_ascent is not None else None,
                "avg_heart_rate": int(avg_hr) if avg_hr is not None else None,
                "max_heart_rate": int(max_hr) if max_hr is not None else None,
                "avg_pace_sec": speed_to_pace(avg_speed),
                "avg_cadence": avg_cadence,
                "temperature": float(temperature) if temperature is not None else None,
                "training_load": float(training_load) if training_load is not None else None,
                "humidity": None,       # Placeholder — backfill via weather API
                "air_pressure": None,   # Placeholder — backfill via weather API
            }
            # Only process the first session message
            break

    if session_data is None:
        return None  # No session found — not a workout file

    # -----------------------------------------------------------------------
    # Pass 2: Extract per-second record data for time-series arrays
    # -----------------------------------------------------------------------
    hr_array = []
    pace_array = []
    first_lat = None
    first_lng = None

    with fitdecode.FitReader(filepath) as fit:
        for frame in fit:
            if frame.frame_type != fitdecode.FIT_FRAME_DATA:
                continue
            if frame.name != "record":
                continue

            # Heart rate
            hr = frame.get_value("heart_rate", fallback=None)
            if hr is not None:
                hr_array.append(int(hr))

            # Speed → pace (sec/km)
            speed = (
                frame.get_value("enhanced_speed", fallback=None)
                or frame.get_value("speed", fallback=None)
            )
            pace = speed_to_pace(speed)
            if pace is not None:
                pace_array.append(pace)

            # Capture the first valid GPS coordinate for weather API lookups
            if first_lat is None:
                lat_raw = frame.get_value("position_lat", fallback=None)
                lng_raw = frame.get_value("position_long", fallback=None)
                if lat_raw is not None and lng_raw is not None:
                    first_lat = semicircles_to_degrees(lat_raw)
                    first_lng = semicircles_to_degrees(lng_raw)

    session_data["start_lat"] = round(first_lat, 6) if first_lat is not None else None
    session_data["start_lng"] = round(first_lng, 6) if first_lng is not None else None
    session_data["hr_array_json"] = json.dumps(hr_array) if hr_array else None
    session_data["pace_array_json"] = json.dumps(pace_array) if pace_array else None

    return session_data


# ===========================================================================
# Main import logic
# ===========================================================================

def import_all_fit_files(data_dir, pid):
    """
    Scan `data_dir` for .fit files and import each into the Activity table.

    - Files without a session message are skipped (not workout data).
    - Files that have already been imported (duplicate `source_file`) are
      caught via IntegrityError and reported as "skipped".
    - A per-file summary is printed to stdout for monitoring.

    Args:
        data_dir: Path to the directory containing .fit files.
        pid: The user/person ID to assign to all imported activities.
    """
    # Ensure database tables exist before importing
    Base.metadata.create_all(bind=engine)

    fit_files = sorted(
        f for f in os.listdir(data_dir) if f.lower().endswith(".fit")
    )

    if not fit_files:
        print(f"No .fit files found in {data_dir}")
        return

    print(f"Found {len(fit_files)} .fit files in {data_dir}")
    print("-" * 60)

    imported = 0
    skipped_dup = 0
    skipped_no_session = 0
    errors = 0

    db = SessionLocal()
    try:
        for i, filename in enumerate(fit_files, 1):
            filepath = os.path.join(data_dir, filename)
            prefix = f"[{i}/{len(fit_files)}]"

            # --- Parse the file ---
            try:
                data = parse_fit_file(filepath)
            except Exception as e:
                print(f"{prefix} ERROR  {filename}: {e}")
                errors += 1
                continue

            if data is None:
                # No session message — skip silently (non-workout file)
                skipped_no_session += 1
                continue

            # --- Build the Activity ORM object ---
            activity = Activity(
                pid=pid,
                source_file=filename,
                **data,
            )

            # --- Insert with duplicate detection ---
            db.add(activity)
            try:
                db.commit()
                imported += 1
                print(
                    f"{prefix} OK     {filename}  "
                    f"{data['type']:5s}  {data['distance_km']:.1f}km  "
                    f"{data['duration_min']:.0f}min  "
                    f"HR={data['avg_heart_rate'] or '?'}"
                )
            except IntegrityError:
                db.rollback()
                skipped_dup += 1
                # Don't spam output for duplicates — only log if verbose
    finally:
        db.close()

    # --- Print summary ---
    print("-" * 60)
    print(f"Import complete:")
    print(f"  Imported:           {imported}")
    print(f"  Skipped (duplicate):{skipped_dup}")
    print(f"  Skipped (no data):  {skipped_no_session}")
    print(f"  Errors:             {errors}")
    print(f"  Total files:        {len(fit_files)}")


# ===========================================================================
# CLI entry point
# ===========================================================================

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Import Coros .fit files into the EnduranceLife database."
    )
    parser.add_argument(
        "--dir",
        default=DEFAULT_DATA_DIR,
        help=f"Directory containing .fit files (default: {DEFAULT_DATA_DIR})",
    )
    parser.add_argument(
        "--pid",
        type=int,
        default=1,
        help="User/person ID to assign to imported activities (default: 1)",
    )
    args = parser.parse_args()

    import_all_fit_files(args.dir, args.pid)

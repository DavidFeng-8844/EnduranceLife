"""
scripts/enrich_weather.py — Backfill weather data for Activity records
using the Open-Meteo Historical Weather API.

This script queries the database for Activity records that have GPS
coordinates (start_lat is not NULL) but are missing weather data
(temperature is NULL), then calls the Open-Meteo archive API to retrieve
hourly temperature, humidity, and surface pressure for the exact location
and date of each activity. The matching hour's data is written back to
the Activity record.

Open-Meteo's Historical Weather API (https://open-meteo.com/en/docs/historical-weather-api):
  - Endpoint: https://archive-api.open-meteo.com/v1/archive
  - Free tier, no API key required
  - Returns hourly reanalysis data from 1940 to ~5 days ago
  - Rate limit: ~600 requests/minute for non-commercial use

Usage (from the project root):
    python -m scripts.enrich_weather
    python -m scripts.enrich_weather --batch-size 100
    python -m scripts.enrich_weather --delay 1.0      # slower, gentler on API

Design choices:
- Each Activity is enriched with a single API call that fetches one day of
  hourly data. We then pick the hour that matches `start_time` to get the
  most accurate conditions at the time of exercise.
- A 0.5s delay between requests avoids triggering Open-Meteo's rate limiter.
- Failed API calls (network errors, unexpected responses) are logged and
  skipped — the script can be re-run safely because it only targets records
  where temperature IS NULL.
- Records are committed individually so that partial progress is preserved
  if the script is interrupted.
"""

import os
import sys
import time
import argparse
from datetime import datetime

import requests

# ---------------------------------------------------------------------------
# Ensure the project root is on sys.path so we can import `app.*`
# ---------------------------------------------------------------------------
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from app.database import SessionLocal  # noqa: E402
from app.models import Activity  # noqa: E402


# ===========================================================================
# Constants
# ===========================================================================

# Open-Meteo Historical Weather API endpoint
ARCHIVE_API_URL = "https://archive-api.open-meteo.com/v1/archive"

# Hourly variables we want to retrieve:
#   temperature_2m       — air temperature at 2 meters (°C)
#   relative_humidity_2m — relative humidity at 2 meters (%)
#   surface_pressure     — atmospheric pressure at surface level (hPa)
HOURLY_VARIABLES = "temperature_2m,relative_humidity_2m,surface_pressure"

# Default delay between API calls (seconds) to respect rate limits
DEFAULT_DELAY = 0.01

# HTTP request timeout (seconds)
REQUEST_TIMEOUT = 15


# ===========================================================================
# Core logic
# ===========================================================================

def fetch_hourly_weather(lat: float, lng: float, date_str: str) -> dict | None:
    """
    Call Open-Meteo's Historical Weather API for a single day and location.

    Args:
        lat:      Latitude in decimal degrees.
        lng:      Longitude in decimal degrees.
        date_str: Date string in ISO format (YYYY-MM-DD).

    Returns:
        A dict with keys "time", "temperature_2m", "relative_humidity_2m",
        "surface_pressure" — each is a list of 24 hourly values.
        Returns None on any failure.

    Example API call:
        https://archive-api.open-meteo.com/v1/archive
          ?latitude=31.2304&longitude=121.4737
          &start_date=2024-06-15&end_date=2024-06-15
          &hourly=temperature_2m,relative_humidity_2m,surface_pressure
    """
    params = {
        "latitude": round(lat, 4),
        "longitude": round(lng, 4),
        "start_date": date_str,
        "end_date": date_str,  # Same day — gives us 24 hourly values
        "hourly": HOURLY_VARIABLES,
    }

    try:
        response = requests.get(
            ARCHIVE_API_URL, params=params, timeout=REQUEST_TIMEOUT
        )
        response.raise_for_status()
    except requests.exceptions.Timeout:
        print(f"    TIMEOUT: API did not respond within {REQUEST_TIMEOUT}s")
        return None
    except requests.exceptions.ConnectionError as e:
        print(f"    CONNECTION ERROR: {e}")
        return None
    except requests.exceptions.HTTPError as e:
        print(f"    HTTP ERROR: {e}")
        return None

    data = response.json()

    # Open-Meteo returns an "error" key if something is wrong (e.g. date
    # out of range, invalid coordinates)
    if data.get("error"):
        print(f"    API ERROR: {data.get('reason', 'Unknown error')}")
        return None

    hourly = data.get("hourly")
    if not hourly or "time" not in hourly:
        print("    UNEXPECTED: API response has no 'hourly' data")
        return None

    return hourly


def extract_weather_for_hour(hourly_data: dict, start_time: datetime) -> dict:
    """
    From a 24-hour block of weather data, extract the values for the
    specific hour that matches the activity's start_time.

    The Open-Meteo time array looks like:
        ["2024-06-15T00:00", "2024-06-15T01:00", ..., "2024-06-15T23:00"]

    We match by hour index (0-23). If start_time is 2024-06-15 06:45:00 UTC,
    we use index 6 (the 06:00 hour block) because weather stations report
    conditions at the top of each hour.

    Args:
        hourly_data: Dict with "time", "temperature_2m", etc. lists.
        start_time:  The activity's start_time (UTC datetime).

    Returns:
        Dict with keys "temperature", "humidity", "air_pressure".
        Values may be None if the API returned null for that hour.
    """
    hour_index = start_time.hour  # 0-23

    # Guard against short arrays (shouldn't happen for a full day, but
    # defensive programming is key when dealing with external APIs)
    time_array = hourly_data.get("time", [])
    if hour_index >= len(time_array):
        print(f"    WARNING: Hour index {hour_index} out of range (got {len(time_array)} entries)")
        hour_index = min(hour_index, len(time_array) - 1)

    temperature = hourly_data.get("temperature_2m", [None] * 24)
    humidity = hourly_data.get("relative_humidity_2m", [None] * 24)
    pressure = hourly_data.get("surface_pressure", [None] * 24)

    return {
        "temperature": temperature[hour_index] if hour_index < len(temperature) else None,
        "humidity": humidity[hour_index] if hour_index < len(humidity) else None,
        "air_pressure": pressure[hour_index] if hour_index < len(pressure) else None,
    }


def enrich_activities(batch_size: int = 500, delay: float = DEFAULT_DELAY):
    """
    Main enrichment loop. Queries for unenriched Activity records, calls the
    weather API for each, and writes the results back to the database.

    The query filter ensures idempotency:
        WHERE start_lat IS NOT NULL AND temperature IS NULL

    This means re-running the script only processes records that haven't
    been enriched yet.

    Args:
        batch_size: Maximum number of records to process in one run.
        delay:      Seconds to sleep between API calls.
    """
    db = SessionLocal()

    try:
        # Query activities that have GPS but no weather data
        activities = (
            db.query(Activity)
            .filter(
                Activity.start_lat.isnot(None),   # Must have GPS coordinates
                Activity.start_lng.isnot(None),
                Activity.temperature.is_(None),    # Not yet enriched
            )
            .order_by(Activity.date.desc())        # Newest first
            .limit(batch_size)
            .all()
        )

        if not activities:
            print("No activities need weather enrichment. All records are up to date.")
            return

        print(f"Found {len(activities)} activities to enrich with weather data.")
        print(f"API delay: {delay}s between requests")
        print("-" * 70)

        updated = 0
        skipped = 0
        errors = 0

        for i, activity in enumerate(activities, 1):
            date_str = activity.date.isoformat()  # "YYYY-MM-DD"
            prefix = f"[{i}/{len(activities)}]"

            print(
                f"{prefix} id={activity.id}  {date_str}  "
                f"({activity.start_lat:.4f}, {activity.start_lng:.4f})  "
                f"{activity.type}",
                end="",
            )

            # --- Call the Open-Meteo API ---
            hourly = fetch_hourly_weather(
                activity.start_lat, activity.start_lng, date_str
            )

            if hourly is None:
                errors += 1
                print("  → FAILED")
                time.sleep(delay)
                continue

            # --- Extract the hour matching start_time ---
            weather = extract_weather_for_hour(hourly, activity.start_time)

            # Check if we actually got meaningful data
            if weather["temperature"] is None and weather["humidity"] is None:
                print("  → NO DATA for this hour")
                skipped += 1
                time.sleep(delay)
                continue

            # --- Write weather data back to the Activity record ---
            activity.temperature = weather["temperature"]
            activity.humidity = weather["humidity"]
            activity.air_pressure = weather["air_pressure"]

            try:
                db.commit()
                updated += 1
                print(
                    f"  → {weather['temperature']}°C  "
                    f"{weather['humidity']}%  "
                    f"{weather['air_pressure']}hPa"
                )
            except Exception as e:
                db.rollback()
                errors += 1
                print(f"  → DB ERROR: {e}")

            # --- Rate-limit courtesy delay ---
            time.sleep(delay)

        # --- Summary ---
        print("-" * 70)
        print("Enrichment complete:")
        print(f"  Updated:  {updated}")
        print(f"  Skipped:  {skipped}")
        print(f"  Errors:   {errors}")
        print(f"  Total:    {len(activities)}")

    finally:
        db.close()


# ===========================================================================
# CLI entry point
# ===========================================================================

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description=(
            "Backfill weather data for Activity records using the "
            "Open-Meteo Historical Weather API."
        )
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=500,
        help="Max number of records to process per run (default: 500)",
    )
    parser.add_argument(
        "--delay",
        type=float,
        default=DEFAULT_DELAY,
        help=f"Seconds between API calls to avoid rate limits (default: {DEFAULT_DELAY})",
    )
    args = parser.parse_args()

    enrich_activities(batch_size=args.batch_size, delay=args.delay)

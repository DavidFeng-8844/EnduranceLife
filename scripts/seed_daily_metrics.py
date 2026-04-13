"""
scripts/seed_daily_metrics.py — Generate simulated DailyMetric records
for every distinct (pid, date) found in the Activity table.

This populates the DailyMetric table with realistic-looking mock data so
the front-end can render charts that cross-reference lifestyle factors
(sleep, fatigue, nutrition) against training performance.

Usage (from the project root):
    python -m scripts.seed_daily_metrics
    python -m scripts.seed_daily_metrics --pid 1

Generated fields and their ranges:
    sleep_hours     — 6.0 to 9.0  (uniform, rounded to 1 decimal)
    fatigue_level   — 1 to 10     (weighted toward 3-6 on rest days,
                                    higher on multi-activity days)
    deep_work_hours — 0.0 to 6.0  (uniform, rounded to 1 decimal)
    calories_in     — 1800 to 3200 (higher on days with more distance)
    protein_g       — 80 to 180
    recovery        — 50.0 to 100.0 %
    stress_level    — 1 to 8

Design choices:
- The script queries distinct (pid, date) pairs from Activity, so every
  day that has at least one workout gets a DailyMetric row.
- Simulated values are influenced by training load: days with longer /
  harder activities get higher fatigue, more calories, lower recovery.
- Existing DailyMetric rows are skipped via IntegrityError on the
  (pid, date) unique constraint, making the script safe to re-run.
"""

import os
import sys
import random
import argparse

from sqlalchemy import func
from sqlalchemy.exc import IntegrityError

# ---------------------------------------------------------------------------
# Ensure the project root is on sys.path so we can import `app.*`
# ---------------------------------------------------------------------------
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from app.database import SessionLocal, engine, Base  # noqa: E402
from app.models import Activity, DailyMetric  # noqa: E402


def generate_daily_metric(pid, date, total_distance_km, total_duration_min):
    """
    Create a DailyMetric object with simulated values.

    The simulation uses the day's total training volume (distance and
    duration summed across all activities) to produce correlated data:
    - Harder training days → higher fatigue, more calories, lower recovery.
    - Rest / easy days → lower fatigue, better recovery, moderate calories.

    Args:
        pid:                User ID.
        date:               The activity date.
        total_distance_km:  Sum of distance_km across all activities that day.
        total_duration_min: Sum of duration_min across all activities that day.

    Returns:
        A DailyMetric ORM instance ready for insertion.
    """
    # Intensity factor: 0.0 (easy day) to 1.0 (very hard day)
    # A 20km / 120min day is considered "hard"
    intensity = min(1.0, (total_distance_km / 20.0 + total_duration_min / 120.0) / 2.0)

    # Sleep: harder days → slightly less sleep (training excitement / soreness)
    sleep_hours = round(random.uniform(6.0, 9.0) - intensity * 0.5, 1)
    sleep_hours = max(5.5, min(9.5, sleep_hours))

    # Fatigue: base 2-5, scales up with intensity
    base_fatigue = random.randint(2, 5)
    fatigue_level = min(10, base_fatigue + int(intensity * 5))

    # Recovery: inversely correlated with intensity
    recovery = round(random.uniform(60.0, 100.0) - intensity * 30.0, 1)
    recovery = max(30.0, min(100.0, recovery))

    # Calories: base 1800-2200, more on hard training days
    calories_in = random.randint(1800, 2200) + int(intensity * 1000)

    # Protein: 80-130g base, higher on hard days
    protein_g = random.randint(80, 130) + int(intensity * 50)

    # Deep work hours: less time for focused work on heavy training days
    deep_work_hours = round(random.uniform(1.0, 6.0) - intensity * 2.0, 1)
    deep_work_hours = max(0.0, deep_work_hours)

    # Stress: loosely correlated with fatigue
    stress_level = min(10, max(1, random.randint(1, 5) + int(intensity * 3)))

    return DailyMetric(
        pid=pid,
        date=date,
        sleep_hours=sleep_hours,
        fatigue_level=fatigue_level,
        recovery=recovery,
        calories_in=calories_in,
        protein_g=protein_g,
        deep_work_hours=deep_work_hours,
        stress_level=stress_level,
    )


def seed_daily_metrics(pid_filter=None):
    """
    Query all distinct (pid, date) pairs from Activity and insert a
    simulated DailyMetric row for each, using batch commits for speed.

    Args:
        pid_filter: If set, only process activities for this user ID.
    """
    BATCH_SIZE = 50

    Base.metadata.create_all(bind=engine)

    db = SessionLocal()
    try:
        # Pre-load existing (pid, date) for fast duplicate check
        existing = set(
            (row[0], row[1])
            for row in db.query(DailyMetric.pid, DailyMetric.date).all()
        )
        print(f"Existing DailyMetric records: {len(existing)}")

        # Aggregate training volume per (pid, date)
        query = (
            db.query(
                Activity.pid,
                Activity.date,
                func.sum(Activity.distance_km).label("total_dist"),
                func.sum(Activity.duration_min).label("total_dur"),
            )
            .group_by(Activity.pid, Activity.date)
            .order_by(Activity.date)
        )

        if pid_filter is not None:
            query = query.filter(Activity.pid == pid_filter)

        day_summaries = query.all()

        if not day_summaries:
            print("No activity dates found in the database.")
            return

        total = len(day_summaries)
        print(f"Found {total} unique (pid, date) pairs from Activity table.")
        print("-" * 60)

        inserted = 0
        skipped = 0
        pending = []

        for i, (pid, date, total_dist, total_dur) in enumerate(day_summaries, 1):
            if (pid, date) in existing:
                skipped += 1
                continue

            metric = generate_daily_metric(
                pid=pid,
                date=date,
                total_distance_km=total_dist or 0,
                total_duration_min=total_dur or 0,
            )
            pending.append(metric)
            existing.add((pid, date))

            if i % 100 == 0 or i == total:
                print(f"[{i}/{total}] processing... ({len(pending)} queued)")

            if len(pending) >= BATCH_SIZE:
                db.add_all(pending)
                db.commit()
                inserted += len(pending)
                pending.clear()

        # Flush remaining
        if pending:
            db.add_all(pending)
            db.commit()
            inserted += len(pending)
            pending.clear()

        print("-" * 60)
        print(f"Seeding complete:")
        print(f"  Inserted: {inserted}")
        print(f"  Skipped (already exists): {skipped}")
        print(f"  Total dates: {total}")

    finally:
        db.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Seed DailyMetric table with simulated data for all Activity dates."
    )
    parser.add_argument(
        "--pid",
        type=int,
        default=None,
        help="Only generate metrics for this user ID (default: all users)",
    )
    args = parser.parse_args()

    seed_daily_metrics(pid_filter=args.pid)

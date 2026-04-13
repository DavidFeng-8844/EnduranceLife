"""
scripts/seed_physiology.py — Generate simulated PhysiologyLog records
with realistic long-term fitness progression trends.

Starting from the user's earliest Activity date, a snapshot is generated
every 14 days up to today. Each snapshot builds on the previous one with
small random increments that simulate gradual athletic improvement:
  - VO2Max slowly rises (aerobic capacity improves with training)
  - Resting heart rate slowly drops (cardiac efficiency improves)
  - Weight slowly decreases (body composition changes)
  - Threshold HR and pace zones shift accordingly

Usage (from the project root):
    python -m scripts.seed_physiology
    python -m scripts.seed_physiology --pid 1

Design choices:
- Progression is cumulative: each row is derived from the previous row's
  values plus a small random delta, producing a believable trend line.
- HR zones and pace zones are recalculated from the evolving threshold
  values so the JSON stays internally consistent over time.
- Running fitness is derived as a composite of VO2Max and resting HR.
- The script is idempotent — re-running skips dates that already exist
  via IntegrityError handling (commit per row).
"""

import json
import os
import sys
import random
import argparse
from datetime import date, timedelta

from sqlalchemy import func
from sqlalchemy.exc import IntegrityError

# ---------------------------------------------------------------------------
# Ensure the project root is on sys.path so we can import `app.*`
# ---------------------------------------------------------------------------
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from app.database import SessionLocal, engine, Base  # noqa: E402
from app.models import Activity, PhysiologyLog  # noqa: E402


# ===========================================================================
# Initial physiological baselines (before training adaptation)
# ===========================================================================
INITIAL_VO2MAX = 42.0           # mL/kg/min — average untrained male
INITIAL_RESTING_HR = 65         # bpm
INITIAL_WEIGHT_KG = 65.0        # kg
INITIAL_HEIGHT_CM = 165.0       # cm — constant (adults don't grow)
INITIAL_THRESHOLD_HR = 170      # bpm — lactate threshold heart rate
INITIAL_THRESHOLD_PACE = 300    # sec/km — 5:00/km threshold pace

SNAPSHOT_INTERVAL_DAYS = 14     # One snapshot every two weeks


# ===========================================================================
# Zone calculation helpers
# ===========================================================================

def compute_hr_zones(threshold_hr: int) -> dict:
    """
    Derive 5 heart-rate training zones from the lactate threshold HR.

    Zone model (percentage of threshold HR):
        Z1 (Recovery):   55-72%
        Z2 (Aerobic):    72-82%
        Z3 (Tempo):      82-90%
        Z4 (Threshold):  90-100%
        Z5 (VO2Max):     100-110%

    Returns a dict like {"z1": "94-122", "z2": "122-139", ...}.
    """
    pcts = [
        ("z1", 0.55, 0.72),
        ("z2", 0.72, 0.82),
        ("z3", 0.82, 0.90),
        ("z4", 0.90, 1.00),
        ("z5", 1.00, 1.10),
    ]
    zones = {}
    for name, lo, hi in pcts:
        zones[name] = f"{int(threshold_hr * lo)}-{int(threshold_hr * hi)}"
    return zones


def compute_pace_zones(threshold_pace_sec: int) -> dict:
    """
    Derive 5 pace training zones from the lactate threshold pace (sec/km).

    Zone model (percentage of threshold pace — note: slower = higher number):
        Z1 (Recovery):   130-145% of threshold pace (very slow)
        Z2 (Aerobic):    113-130%
        Z3 (Tempo):      102-113%
        Z4 (Threshold):  97-102%
        Z5 (VO2Max):     85-97%  (faster than threshold)

    Returns a dict with pace ranges formatted as "M:SS-M:SS".
    """
    pcts = [
        ("z1", 1.30, 1.45),
        ("z2", 1.13, 1.30),
        ("z3", 1.02, 1.13),
        ("z4", 0.97, 1.02),
        ("z5", 0.85, 0.97),
    ]
    zones = {}
    for name, lo, hi in pcts:
        lo_sec = int(threshold_pace_sec * lo)
        hi_sec = int(threshold_pace_sec * hi)
        lo_fmt = f"{lo_sec // 60}:{lo_sec % 60:02d}"
        hi_fmt = f"{hi_sec // 60}:{hi_sec % 60:02d}"
        zones[name] = f"{lo_fmt}-{hi_fmt}"
    return zones


# ===========================================================================
# Core seeding logic
# ===========================================================================

def seed_physiology(pid: int = 1):
    """
    Generate bi-weekly PhysiologyLog snapshots with batch commits.
    """
    BATCH_SIZE = 50

    Base.metadata.create_all(bind=engine)
    db = SessionLocal()

    try:
        # Pre-load existing dates for fast duplicate check
        existing = set(
            row[0] for row in
            db.query(PhysiologyLog.date).filter(PhysiologyLog.pid == pid).all()
        )
        print(f"Existing PhysiologyLog records for pid={pid}: {len(existing)}")

        earliest = (
            db.query(func.min(Activity.date))
            .filter(Activity.pid == pid)
            .scalar()
        )

        if earliest is None:
            print(f"No Activity records found for pid={pid}. Nothing to seed.")
            return

        today = date.today()
        print(f"Generating PhysiologyLog for pid={pid}")
        print(f"  Date range: {earliest} -> {today}")
        total_days = (today - earliest).days
        expected_rows = total_days // SNAPSHOT_INTERVAL_DAYS + 1
        print(f"  Interval: every {SNAPSHOT_INTERVAL_DAYS} days (~{expected_rows} snapshots)")
        print("-" * 65)

        # Initialize evolving state
        vo2max = INITIAL_VO2MAX
        resting_hr = float(INITIAL_RESTING_HR)
        weight_kg = INITIAL_WEIGHT_KG
        threshold_hr = float(INITIAL_THRESHOLD_HR)
        threshold_pace = float(INITIAL_THRESHOLD_PACE)

        current_date = earliest
        inserted = 0
        skipped = 0
        pending = []

        while current_date <= today:
            # Apply random progression deltas (must always run to keep state consistent)
            vo2max += random.uniform(-0.1, 0.4)
            vo2max = round(max(38.0, min(65.0, vo2max)), 1)

            resting_hr += random.uniform(-0.5, 0.2)
            resting_hr = max(38.0, min(75.0, resting_hr))

            weight_kg += random.uniform(-0.3, 0.15)
            weight_kg = round(max(55.0, min(75.0, weight_kg)), 1)

            threshold_hr += random.uniform(-0.3, 0.5)
            threshold_hr = max(160.0, min(190.0, threshold_hr))

            threshold_pace += random.uniform(-2.0, 0.5)
            threshold_pace = max(220.0, min(360.0, threshold_pace))

            running_fitness = round(vo2max * 1.2 - resting_hr * 0.3 + random.uniform(-1, 1), 1)

            if current_date not in existing:
                hr_zones = compute_hr_zones(int(threshold_hr))
                pace_zones = compute_pace_zones(int(threshold_pace))

                log = PhysiologyLog(
                    pid=pid,
                    date=current_date,
                    height_cm=INITIAL_HEIGHT_CM,
                    weight_kg=weight_kg,
                    running_fitness=running_fitness,
                    vo2max=vo2max,
                    resting_heart_rate=int(round(resting_hr)),
                    threshold_hr_zones=json.dumps(hr_zones),
                    threshold_pace_zones=json.dumps(pace_zones),
                )
                pending.append(log)
                existing.add(current_date)
            else:
                skipped += 1

            if len(pending) >= BATCH_SIZE:
                db.add_all(pending)
                db.commit()
                inserted += len(pending)
                print(f"  Committed batch ({inserted} inserted so far)")
                pending.clear()

            current_date += timedelta(days=SNAPSHOT_INTERVAL_DAYS)

        # Flush remaining
        if pending:
            db.add_all(pending)
            db.commit()
            inserted += len(pending)
            pending.clear()

        # Summary
        print("-" * 65)
        print(f"Seeding complete:")
        print(f"  Inserted:  {inserted}")
        print(f"  Skipped:   {skipped} (already existed)")
        print(f"  Final VO2Max:       {vo2max}")
        print(f"  Final Resting HR:   {int(resting_hr)}")
        print(f"  Final Weight:       {weight_kg} kg")

    finally:
        db.close()


# ===========================================================================
# CLI entry point
# ===========================================================================

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Seed PhysiologyLog table with trending simulated data."
    )
    parser.add_argument(
        "--pid",
        type=int,
        default=1,
        help="User/person ID (default: 1)",
    )
    args = parser.parse_args()

    seed_physiology(pid=args.pid)

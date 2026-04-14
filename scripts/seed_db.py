"""
seed_db.py — Autoseeder for Cloud Deployments (Render)

This script checks if the database has any Activity data. 
If it is empty, it automatically triggers the three seed commands:
1. import_fit
2. seed_physiology
3. seed_daily_metrics

This guarantees that when an examiner opens the Render URL, 
the demo user (pid=1) instantly has a fully populated dashboard.
"""

import sys
import subprocess
from app.database import SessionLocal
from app.models import Activity

def is_db_empty():
    db = SessionLocal()
    try:
        count = db.query(Activity).count()
        return count == 0
    except Exception as e:
        print(f"Database error: {e}")
        return True
    finally:
        db.close()

def main():
    print("Checking database state...")
    if not is_db_empty():
        print("Database already contains data. Skipping seed phase.")
        return

    print("Database is empty. Initiating automatic data seeding for 'demo' user...")
    
    commands = [
        ["python", "-m", "scripts.import_fit", "data/coros"],
        ["python", "-m", "scripts.seed_physiology", "--pid", "1"],
        ["python", "-m", "scripts.seed_daily_metrics", "--pid", "1"]
    ]

    for cmd in commands:
        print(f"Running: {' '.join(cmd)}")
        result = subprocess.run(cmd)
        if result.returncode != 0:
            print(f"Error running {' '.join(cmd)}. Exiting.")
            sys.exit(1)

    print("✅ Database successfully seeded with demo data!")

if __name__ == "__main__":
    main()

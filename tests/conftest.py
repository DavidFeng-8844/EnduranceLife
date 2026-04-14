"""
tests/conftest.py — Shared pytest fixtures for the EnduranceLife test suite.

All tests run against an **in-memory SQLite database** that is created fresh
for every test function, ensuring complete isolation between tests and zero
impact on the production database.

Key fixtures:
    db_session  — a scoped SQLAlchemy session bound to in-memory SQLite
    client      — a FastAPI TestClient with the DB dependency overridden
    sample_activity / sample_daily_metric / sample_physiology_log
                — pre-inserted ORM objects for read/update/delete tests
"""

import os
import pytest
from datetime import date, datetime, timezone

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

# Ensure project root is importable
import sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.database import Base, get_db
from app.main import app
from app import models


# ---------------------------------------------------------------------------
# In-memory SQLite engine + session factory — created once per test session
# but each test function gets its own transaction via the db_session fixture.
# ---------------------------------------------------------------------------
TEST_ENGINE = create_engine(
    "sqlite://",  # in-memory
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestSessionLocal = sessionmaker(bind=TEST_ENGINE, autocommit=False, autoflush=False)


# ---------------------------------------------------------------------------
# Core fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def db_session():
    """
    Yield a clean database session for each test.

    Tables are created before and dropped after every test to guarantee
    full isolation — no state leaks between tests.
    """
    Base.metadata.create_all(bind=TEST_ENGINE)
    session = TestSessionLocal()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(bind=TEST_ENGINE)


@pytest.fixture()
def client(db_session):
    """
    FastAPI TestClient with the DB dependency overridden to use the
    in-memory test database instead of the production SQLite file.
    
    Automatically creates a demo user (pid=1) and attaches a JWT Bearer 
    token so tests hitting protected endpoints pass smoothly.
    """
    def _override_get_db():
        try:
            yield db_session
        finally:
            pass

    app.dependency_overrides[get_db] = _override_get_db
    with TestClient(app) as c:
        # 1. Create default user
        from app.auth import hash_password
        user = models.User(username="demo", hashed_password=hash_password("endurance2026"))
        db_session.add(user)
        db_session.commit()
        db_session.refresh(user)
        
        # 2. Login to get token
        resp = c.post("/auth/login", data={"username": "demo", "password": "endurance2026"})
        if resp.status_code == 200:
            token = resp.json()["access_token"]
            c.headers.update({"Authorization": f"Bearer {token}"})
            
        yield c
        
    app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# Sample data factories
# ---------------------------------------------------------------------------

@pytest.fixture()
def sample_activity(db_session):
    """Insert and return a sample Activity for tests that need existing data."""
    activity = models.Activity(
        pid=1,
        source_file="test_run_001.fit",
        date=date(2024, 6, 15),
        start_time=datetime(2024, 6, 15, 6, 30, 0, tzinfo=timezone.utc),
        start_lat=31.2304,
        start_lng=121.4737,
        distance_km=10.5,
        duration_min=55.0,
        type="Run",
        temperature=22.5,
        humidity=65.0,
        air_pressure=1013.2,
        altitude_gain=50.0,
        avg_heart_rate=155,
        max_heart_rate=178,
        avg_pace_sec=314,
        avg_cadence=174,
        training_load=85.0,
        hr_array_json="[120,130,145,155,160,158,155,150]",
        pace_array_json="[350,330,315,310,305,310,320,330]",
    )
    db_session.add(activity)
    db_session.commit()
    db_session.refresh(activity)
    return activity


@pytest.fixture()
def sample_ride(db_session):
    """Insert and return a sample Ride Activity."""
    ride = models.Activity(
        pid=1,
        source_file="test_ride_001.fit",
        date=date(2024, 6, 16),
        start_time=datetime(2024, 6, 16, 7, 0, 0, tzinfo=timezone.utc),
        start_lat=31.23,
        start_lng=121.47,
        distance_km=42.0,
        duration_min=90.0,
        type="Ride",
        avg_heart_rate=135,
        max_heart_rate=160,
    )
    db_session.add(ride)
    db_session.commit()
    db_session.refresh(ride)
    return ride


@pytest.fixture()
def sample_daily_metric(db_session):
    """Insert and return a sample DailyMetric."""
    metric = models.DailyMetric(
        pid=1,
        date=date(2024, 6, 15),
        calories_in=2200,
        protein_g=120,
        sleep_hours=7.5,
        fatigue_level=4,
        recovery=75.0,
        deep_work_hours=3.5,
        stress_level=3,
    )
    db_session.add(metric)
    db_session.commit()
    db_session.refresh(metric)
    return metric


@pytest.fixture()
def sample_physiology_log(db_session):
    """Insert and return a sample PhysiologyLog."""
    log = models.PhysiologyLog(
        pid=1,
        date=date(2024, 6, 15),
        height_cm=177.0,
        weight_kg=65.0,
        running_fitness=45.0,
        vo2max=52.0,
        resting_heart_rate=55,
        threshold_hr_zones='{"z1":"94-122","z2":"122-139","z3":"139-153","z4":"153-170","z5":"170-187"}',
        threshold_pace_zones='{"z1":"6:30-7:15","z2":"5:39-6:30","z3":"5:06-5:39","z4":"4:51-5:06","z5":"4:15-4:51"}',
    )
    db_session.add(log)
    db_session.commit()
    db_session.refresh(log)
    return log


# ---------------------------------------------------------------------------
# Multi-record fixtures for analytics tests
# ---------------------------------------------------------------------------

@pytest.fixture()
def analytics_data(db_session):
    """
    Insert a realistic mix of activities and daily metrics for testing
    analytics endpoints. Returns a dict of created objects.
    """
    activities = []
    metrics = []

    # Activities across temperature ranges and types
    test_data = [
        # (date, type, dist, dur, hr, pace, temp, humidity, pressure, load)
        (date(2024, 1, 10), "Run", 8.0, 45.0, 145, 337, 5.0, 70.0, 1020.0, 60.0),   # Cold
        (date(2024, 1, 15), "Run", 10.0, 52.0, 150, 312, 3.0, 75.0, 1015.0, 75.0),   # Cold
        (date(2024, 3, 20), "Run", 12.0, 60.0, 155, 300, 15.0, 60.0, 1013.0, 85.0),  # Moderate
        (date(2024, 3, 25), "Run", 5.0, 25.0, 160, 300, 18.0, 55.0, 1010.0, 50.0),   # Moderate
        (date(2024, 6, 10), "Run", 8.0, 42.0, 165, 315, 30.0, 80.0, 1008.0, 70.0),   # Hot
        (date(2024, 6, 15), "Run", 6.0, 35.0, 170, 350, 32.0, 85.0, 1005.0, 55.0),   # Hot
        (date(2024, 6, 16), "Ride", 40.0, 90.0, 130, None, 28.0, 65.0, 1010.0, 80.0), # Ride
        (date(2024, 6, 17), "Run", 2.0, 12.0, 120, 360, 20.0, 50.0, 1012.0, 20.0),   # Short run (<3km)
    ]

    for d, typ, dist, dur, hr, pace, temp, hum, pres, load in test_data:
        a = models.Activity(
            pid=1,
            source_file=f"analytics_{d.isoformat()}_{typ}.fit",
            date=d,
            start_time=datetime(d.year, d.month, d.day, 7, 0, tzinfo=timezone.utc),
            start_lat=31.23,
            start_lng=121.47,
            distance_km=dist,
            duration_min=dur,
            type=typ,
            temperature=temp,
            humidity=hum,
            air_pressure=pres,
            avg_heart_rate=hr,
            max_heart_rate=hr + 20,
            avg_pace_sec=pace,
            training_load=load,
        )
        db_session.add(a)
        activities.append(a)

    # Matching DailyMetrics for lifestyle analysis
    metric_data = [
        # (date, sleep, fatigue)
        (date(2024, 1, 10), 8.0, 3),   # Good sleep, low fatigue
        (date(2024, 1, 15), 8.5, 2),   # Good sleep, low fatigue
        (date(2024, 3, 20), 6.5, 5),   # Poor sleep, medium fatigue
        (date(2024, 3, 25), 7.0, 8),   # Poor sleep, high fatigue
        (date(2024, 6, 10), 7.5, 7),   # Good sleep, high fatigue
        (date(2024, 6, 15), 6.0, 9),   # Poor sleep, high fatigue
        (date(2024, 6, 17), 8.0, 3),   # Good sleep, low fatigue
    ]

    for d, sleep, fatigue in metric_data:
        m = models.DailyMetric(
            pid=1,
            date=d,
            sleep_hours=sleep,
            fatigue_level=fatigue,
            calories_in=2200,
            protein_g=120,
            recovery=70.0,
        )
        db_session.add(m)
        metrics.append(m)

    db_session.commit()
    return {"activities": activities, "metrics": metrics}

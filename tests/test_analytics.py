"""
tests/test_analytics.py — Tests for all 5 analytics dashboard endpoints.

Coverage:
    GET /analytics/physiology/trends      (trend data + race predictor)
    GET /analytics/performance/records    (PRs: longest run/ride, best pace)
    GET /analytics/training/status        (daily summary + intensity distribution)
    GET /analytics/insights/environment   (temperature zone analysis)
    GET /analytics/insights/lifestyle     (sleep + fatigue impact)
"""

import pytest


# ===========================================================================
# GET /analytics/physiology/trends
# ===========================================================================

class TestPhysiologyTrends:
    def test_trends_empty(self, client):
        r = client.get("/analytics/physiology/trends?pid=1")
        assert r.status_code == 200
        data = r.json()
        assert data["trends"] == []
        assert data["current_status"] is None
        assert data["race_predictor"] is None

    def test_trends_with_data(self, client, sample_physiology_log):
        r = client.get("/analytics/physiology/trends?pid=1&limit=5")
        assert r.status_code == 200
        data = r.json()
        assert len(data["trends"]) == 1
        assert data["trends"][0]["vo2max"] == 52.0
        assert data["trends"][0]["resting_heart_rate"] == 55

    def test_current_status_has_zones(self, client, sample_physiology_log):
        r = client.get("/analytics/physiology/trends?pid=1")
        data = r.json()
        status = data["current_status"]
        assert status is not None
        assert "z1" in status["threshold_hr_zones"]
        assert "z1" in status["threshold_pace_zones"]

    def test_race_predictor(self, client, sample_physiology_log):
        r = client.get("/analytics/physiology/trends?pid=1")
        data = r.json()
        predictor = data["race_predictor"]
        assert predictor is not None
        assert predictor["vo2max_used"] == 52.0
        # Should be in H:MM:SS format
        assert ":" in predictor["predicted_5k"]
        assert ":" in predictor["predicted_10k"]
        assert ":" in predictor["predicted_half_marathon"]


# ===========================================================================
# GET /analytics/performance/records
# ===========================================================================

class TestPerformanceRecords:
    def test_records_empty(self, client):
        r = client.get("/analytics/performance/records?pid=1")
        assert r.status_code == 200
        data = r.json()
        assert data["run_records"] == []
        assert data["ride_records"] == []

    def test_5k_record(self, client, db_session):
        """A 5.1km run should register as a 5K PR."""
        from datetime import date as d, datetime, timezone
        from app import models

        db_session.add(models.Activity(
            pid=1, source_file="5k.fit", date=d(2024, 6, 1),
            start_time=datetime(2024, 6, 1, 7, 0, tzinfo=timezone.utc),
            distance_km=5.1, duration_min=22.0, type="Run",
            avg_heart_rate=170, avg_pace_sec=259,  # 4:19/km
        ))
        db_session.commit()

        r = client.get("/analytics/performance/records?pid=1")
        runs = r.json()["run_records"]
        labels = [rec["label"] for rec in runs]
        assert "5K" in labels
        rec = next(rec for rec in runs if rec["label"] == "5K")
        assert rec["actual_km"] == 5.1
        assert ":" in rec["duration_formatted"]
        assert rec["avg_pace_formatted"] == "4:19"

    def test_anomalous_pace_excluded(self, client, db_session):
        """A 5K run with impossibly fast pace (< 2:30/km) should be excluded."""
        from datetime import date as d, datetime, timezone
        from app import models

        db_session.add(models.Activity(
            pid=1, source_file="bad5k.fit", date=d(2024, 7, 1),
            start_time=datetime(2024, 7, 1, 7, 0, tzinfo=timezone.utc),
            distance_km=5.0, duration_min=10.0, type="Run",
            avg_heart_rate=150, avg_pace_sec=120,  # 2:00/km — impossible
        ))
        db_session.commit()

        r = client.get("/analytics/performance/records?pid=1")
        runs = r.json()["run_records"]
        assert len(runs) == 0  # Anomalous run excluded

    def test_out_of_band_distance_excluded(self, client, db_session):
        """A 7km run should not match 5K (4.8-5.5) or 10K (9.5-10.5)."""
        from datetime import date as d, datetime, timezone
        from app import models

        db_session.add(models.Activity(
            pid=1, source_file="7k.fit", date=d(2024, 6, 1),
            start_time=datetime(2024, 6, 1, 7, 0, tzinfo=timezone.utc),
            distance_km=7.0, duration_min=35.0, type="Run",
            avg_heart_rate=160, avg_pace_sec=300,  # 5:00/km
        ))
        db_session.commit()

        r = client.get("/analytics/performance/records?pid=1")
        assert r.json()["run_records"] == []

    def test_ride_record(self, client, db_session):
        """A 50km ride should register as a 50km PR."""
        from datetime import date as d, datetime, timezone
        from app import models

        db_session.add(models.Activity(
            pid=1, source_file="ride50.fit", date=d(2024, 6, 1),
            start_time=datetime(2024, 6, 1, 7, 0, tzinfo=timezone.utc),
            distance_km=50.5, duration_min=95.0, type="Ride",  # ~31.9 km/h
            avg_heart_rate=140,
        ))
        db_session.commit()

        r = client.get("/analytics/performance/records?pid=1")
        rides = r.json()["ride_records"]
        labels = [rec["label"] for rec in rides]
        assert "50km" in labels

    def test_fastest_wins(self, client, db_session):
        """When multiple 10K runs exist, the fastest time wins."""
        from datetime import date as d, datetime, timezone
        from app import models

        for i, (dur, pace) in enumerate([(50.0, 300), (45.0, 270)]):
            db_session.add(models.Activity(
                pid=1, source_file=f"10k_{i}.fit", date=d(2024, 6, i+1),
                start_time=datetime(2024, 6, i+1, 7, 0, tzinfo=timezone.utc),
                distance_km=10.0, duration_min=dur, type="Run",
                avg_heart_rate=160, avg_pace_sec=pace,
            ))
        db_session.commit()

        r = client.get("/analytics/performance/records?pid=1")
        runs = r.json()["run_records"]
        rec10k = next(rec for rec in runs if rec["label"] == "10K")
        assert rec10k["duration_min"] == 45.0  # The faster one


# ===========================================================================
# GET /analytics/training/status
# ===========================================================================

class TestTrainingStatus:
    def test_status_empty(self, client):
        r = client.get("/analytics/training/status?pid=1&days=30")
        assert r.status_code == 200
        data = r.json()
        assert data["daily_summary"] == []
        assert data["totals"]["total_activities"] == 0
        # Intensity distribution should always have 3 buckets
        assert len(data["intensity_distribution"]) == 3

    def test_status_with_recent_data(self, client, db_session):
        """Insert an activity within the last 30 days to verify daily summary."""
        from datetime import date as d, datetime, timedelta, timezone
        from app import models

        recent_date = d.today() - timedelta(days=5)
        a = models.Activity(
            pid=1,
            source_file="recent_run.fit",
            date=recent_date,
            start_time=datetime(recent_date.year, recent_date.month, recent_date.day, 7, 0, tzinfo=timezone.utc),
            distance_km=10.0,
            duration_min=50.0,
            type="Run",
            avg_heart_rate=155,
            training_load=80.0,
        )
        db_session.add(a)
        db_session.commit()

        r = client.get("/analytics/training/status?pid=1&days=30")
        data = r.json()
        assert len(data["daily_summary"]) == 1
        assert data["totals"]["total_activities"] == 1
        assert data["totals"]["total_run_km"] == 10.0

    def test_intensity_distribution_buckets(self, client, db_session):
        """Verify Easy/Tempo/Hard bucketing by avg_heart_rate."""
        from datetime import date as d, datetime, timedelta, timezone
        from app import models

        today = d.today()
        activities = [
            ("easy.fit", today - timedelta(days=1), 120),   # Easy < 140
            ("tempo.fit", today - timedelta(days=2), 150),  # Tempo 140-160
            ("hard.fit", today - timedelta(days=3), 175),   # Hard > 160
        ]
        for sf, dt, hr in activities:
            db_session.add(models.Activity(
                pid=1, source_file=sf, date=dt,
                start_time=datetime(dt.year, dt.month, dt.day, 7, 0, tzinfo=timezone.utc),
                distance_km=5.0, duration_min=25.0, type="Run",
                avg_heart_rate=hr,
            ))
        db_session.commit()

        r = client.get("/analytics/training/status?pid=1&days=30")
        dist = {b["zone"]: b["count"] for b in r.json()["intensity_distribution"]}
        assert dist["Easy"] == 1
        assert dist["Tempo"] == 1
        assert dist["Hard"] == 1


# ===========================================================================
# GET /analytics/insights/environment
# ===========================================================================

class TestEnvironmentInsights:
    def test_environment_empty(self, client):
        r = client.get("/analytics/insights/environment?pid=1")
        assert r.status_code == 200
        zones = r.json()["temperature_zones"]
        assert len(zones) == 3
        assert all(z["count"] == 0 for z in zones)

    def test_environment_temperature_zones(self, client, analytics_data):
        r = client.get("/analytics/insights/environment?pid=1")
        zones = {z["zone"]: z for z in r.json()["temperature_zones"]}

        # Cold < 10°C: 2 runs at 5°C and 3°C
        assert zones["Cold"]["count"] == 2
        assert zones["Cold"]["avg_heart_rate"] is not None

        # Moderate 10-22°C: 2 runs at 15°C and 18°C
        # (the 20°C short run has pace so it counts too)
        assert zones["Moderate"]["count"] >= 2

        # Hot > 22°C: 2 runs at 30°C and 32°C
        assert zones["Hot"]["count"] == 2

    def test_environment_excludes_rides(self, client, analytics_data):
        """Only Run type should be included in environment analysis."""
        r = client.get("/analytics/insights/environment?pid=1")
        total = sum(z["count"] for z in r.json()["temperature_zones"])
        # 7 runs in analytics_data (6 normal + 1 short), 1 ride excluded
        assert total <= 7  # Only runs


# ===========================================================================
# GET /analytics/insights/lifestyle
# ===========================================================================

class TestLifestyleInsights:
    def test_lifestyle_empty(self, client):
        r = client.get("/analytics/insights/lifestyle?pid=1")
        assert r.status_code == 200
        data = r.json()
        assert data["sleep_impact"] == []
        assert data["fatigue_impact"] == []

    def test_sleep_impact_groups(self, client, analytics_data):
        r = client.get("/analytics/insights/lifestyle?pid=1")
        sleep = r.json()["sleep_impact"]
        labels = [g["label"] for g in sleep]
        # Should have two groups
        assert len(sleep) >= 1
        # At least one of these should exist
        assert any("Good" in l or "Poor" in l for l in labels)

    def test_fatigue_impact_groups(self, client, analytics_data):
        r = client.get("/analytics/insights/lifestyle?pid=1")
        fatigue = r.json()["fatigue_impact"]
        assert len(fatigue) >= 1
        for group in fatigue:
            assert group["count"] > 0

    def test_lifestyle_only_runs(self, client, analytics_data):
        """Lifestyle insights should only include Run activities."""
        r = client.get("/analytics/insights/lifestyle?pid=1")
        # The ride on 2024-06-16 has no matching DailyMetric,
        # and even if it did, it should be filtered as type != 'Run'
        data = r.json()
        total_sleep = sum(g["count"] for g in data["sleep_impact"])
        total_fatigue = sum(g["count"] for g in data["fatigue_impact"])
        # Max possible runs with matching metrics = 7
        assert total_sleep <= 7
        assert total_fatigue <= 7

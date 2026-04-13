"""
tests/test_daily_metric.py — Tests for DailyMetric CRUD + by-date update.

Coverage:
    - POST   /daily-metrics/          (create + duplicate 409)
    - GET    /daily-metrics/          (list + filters + date range)
    - GET    /daily-metrics/{id}      (single + 404)
    - PUT    /daily-metrics/{id}      (partial update by ID)
    - PUT    /daily-metrics/by-date   (partial update by pid+date + 404)
    - DELETE /daily-metrics/{id}      (delete + 404)
"""

import pytest


# ===========================================================================
# POST /daily-metrics/
# ===========================================================================

class TestCreateDailyMetric:
    def test_create_success(self, client):
        payload = {
            "pid": 1,
            "date": "2024-08-01",
            "calories_in": 2500,
            "protein_g": 150,
            "sleep_hours": 8.0,
            "fatigue_level": 3,
            "recovery": 85.0,
            "deep_work_hours": 4.0,
            "stress_level": 2,
        }
        r = client.post("/daily-metrics/", json=payload)
        assert r.status_code == 201
        data = r.json()
        assert data["pid"] == 1
        assert data["sleep_hours"] == 8.0
        assert "id" in data

    def test_create_duplicate_returns_409(self, client, sample_daily_metric):
        payload = {
            "pid": sample_daily_metric.pid,
            "date": str(sample_daily_metric.date),
            "sleep_hours": 7.0,
        }
        r = client.post("/daily-metrics/", json=payload)
        assert r.status_code == 409
        assert "already exists" in r.json()["detail"]

    def test_create_minimal_fields(self, client):
        """Only pid and date are required; all others are optional."""
        payload = {"pid": 1, "date": "2024-09-01"}
        r = client.post("/daily-metrics/", json=payload)
        assert r.status_code == 201
        assert r.json()["sleep_hours"] is None

    def test_fatigue_level_validation(self, client):
        """fatigue_level must be 1-10."""
        payload = {"pid": 1, "date": "2024-09-02", "fatigue_level": 15}
        r = client.post("/daily-metrics/", json=payload)
        assert r.status_code == 422


# ===========================================================================
# GET /daily-metrics/
# ===========================================================================

class TestListDailyMetrics:
    def test_list_empty(self, client):
        r = client.get("/daily-metrics/")
        assert r.status_code == 200
        assert r.json() == []

    def test_list_with_data(self, client, sample_daily_metric):
        r = client.get("/daily-metrics/")
        assert len(r.json()) == 1

    def test_filter_by_pid(self, client, sample_daily_metric):
        r = client.get("/daily-metrics/?pid=1")
        assert len(r.json()) == 1
        r = client.get("/daily-metrics/?pid=999")
        assert len(r.json()) == 0

    def test_filter_by_date_range(self, client, sample_daily_metric):
        r = client.get("/daily-metrics/?date_from=2024-06-01&date_to=2024-06-30")
        assert len(r.json()) == 1

        r = client.get("/daily-metrics/?date_from=2025-01-01")
        assert len(r.json()) == 0


# ===========================================================================
# GET /daily-metrics/{id}
# ===========================================================================

class TestGetDailyMetric:
    def test_get_existing(self, client, sample_daily_metric):
        r = client.get(f"/daily-metrics/{sample_daily_metric.id}")
        assert r.status_code == 200
        assert r.json()["id"] == sample_daily_metric.id

    def test_get_nonexistent_returns_404(self, client):
        r = client.get("/daily-metrics/99999")
        assert r.status_code == 404


# ===========================================================================
# PUT /daily-metrics/{id}
# ===========================================================================

class TestUpdateDailyMetricById:
    def test_partial_update(self, client, sample_daily_metric):
        r = client.put(
            f"/daily-metrics/{sample_daily_metric.id}",
            json={"sleep_hours": 9.0, "fatigue_level": 2},
        )
        assert r.status_code == 200
        assert r.json()["sleep_hours"] == 9.0
        assert r.json()["fatigue_level"] == 2
        # Unchanged fields preserved
        assert r.json()["calories_in"] == 2200

    def test_update_nonexistent_returns_404(self, client):
        r = client.put("/daily-metrics/99999", json={"sleep_hours": 7.0})
        assert r.status_code == 404


# ===========================================================================
# PUT /daily-metrics/by-date
# ===========================================================================

class TestUpdateDailyMetricByDate:
    def test_update_by_date_success(self, client, sample_daily_metric):
        r = client.put(
            "/daily-metrics/by-date?pid=1&date=2024-06-15",
            json={"sleep_hours": 9.5, "stress_level": 1},
        )
        assert r.status_code == 200
        assert r.json()["sleep_hours"] == 9.5
        assert r.json()["stress_level"] == 1

    def test_update_by_date_nonexistent_returns_404(self, client):
        r = client.put(
            "/daily-metrics/by-date?pid=1&date=2099-01-01",
            json={"sleep_hours": 7.0},
        )
        assert r.status_code == 404


# ===========================================================================
# DELETE /daily-metrics/{id}
# ===========================================================================

class TestDeleteDailyMetric:
    def test_delete_existing(self, client, sample_daily_metric):
        r = client.delete(f"/daily-metrics/{sample_daily_metric.id}")
        assert r.status_code == 204

        r = client.get(f"/daily-metrics/{sample_daily_metric.id}")
        assert r.status_code == 404

    def test_delete_nonexistent_returns_404(self, client):
        r = client.delete("/daily-metrics/99999")
        assert r.status_code == 404

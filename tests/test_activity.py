"""
tests/test_activity.py — Tests for Activity CRUD + .fit file upload.

Coverage:
    - POST   /activities/       (JSON create + duplicate 409)
    - POST   /activities/upload (.fit file upload + parsing + duplicate 409)
    - GET    /activities/       (list + pid/type/date filters + pagination)
    - GET    /activities/{id}   (single read + 404)
    - PUT    /activities/{id}   (partial update + 404)
    - DELETE /activities/{id}   (delete + 404)
"""

import os
import pytest


# ===========================================================================
# POST /activities/ (JSON)
# ===========================================================================

class TestCreateActivity:
    def test_create_success(self, client):
        payload = {
            "pid": 1,
            "source_file": "new_run.fit",
            "date": "2024-07-01",
            "start_time": "2024-07-01T06:00:00Z",
            "distance_km": 8.0,
            "duration_min": 40.0,
            "type": "Run",
        }
        r = client.post("/activities/", json=payload)
        assert r.status_code == 201
        data = r.json()
        assert data["source_file"] == "new_run.fit"
        assert data["distance_km"] == 8.0
        assert data["type"] == "Run"
        assert "id" in data

    def test_create_duplicate_returns_409(self, client, sample_activity):
        payload = {
            "pid": 1,
            "source_file": sample_activity.source_file,  # duplicate
            "date": "2024-06-15",
            "start_time": "2024-06-15T06:30:00Z",
            "distance_km": 5.0,
            "duration_min": 25.0,
            "type": "Run",
        }
        r = client.post("/activities/", json=payload)
        assert r.status_code == 409
        assert "already exists" in r.json()["detail"]

    def test_create_missing_required_field_returns_422(self, client):
        payload = {"pid": 1, "source_file": "x.fit"}  # missing date, start_time, etc.
        r = client.post("/activities/", json=payload)
        assert r.status_code == 422


# ===========================================================================
# POST /activities/upload (.fit file)
# ===========================================================================

class TestUploadFitFile:
    @pytest.fixture()
    def fit_file_path(self):
        """Path to a real .fit file for upload testing."""
        path = os.path.join("data", "coros", "452318074314457088.fit")
        if not os.path.exists(path):
            pytest.skip("Test .fit file not available")
        return path

    def test_upload_success(self, client, fit_file_path):
        with open(fit_file_path, "rb") as f:
            r = client.post(
                "/activities/upload",
                files={"file": ("452318074314457088.fit", f, "application/octet-stream")},
                data={"pid": "1"},
            )
        assert r.status_code == 201
        data = r.json()
        assert data["source_file"] == "452318074314457088.fit"
        assert data["type"] in ("Run", "Ride", "Other")
        assert data["distance_km"] > 0
        assert data["duration_min"] > 0

    def test_upload_duplicate_returns_409(self, client, fit_file_path):
        # First upload
        with open(fit_file_path, "rb") as f:
            client.post(
                "/activities/upload",
                files={"file": ("dup_test.fit", f, "application/octet-stream")},
                data={"pid": "1"},
            )
        # Second upload of same filename
        with open(fit_file_path, "rb") as f:
            r = client.post(
                "/activities/upload",
                files={"file": ("dup_test.fit", f, "application/octet-stream")},
                data={"pid": "1"},
            )
        assert r.status_code == 409

    def test_upload_non_fit_file_returns_422(self, client):
        r = client.post(
            "/activities/upload",
            files={"file": ("readme.txt", b"not a fit file", "text/plain")},
            data={"pid": "1"},
        )
        assert r.status_code == 422
        assert ".fit" in r.json()["detail"]

    def test_upload_empty_file_returns_422(self, client):
        r = client.post(
            "/activities/upload",
            files={"file": ("empty.fit", b"", "application/octet-stream")},
            data={"pid": "1"},
        )
        assert r.status_code == 422


# ===========================================================================
# GET /activities/ (list + filters)
# ===========================================================================

class TestListActivities:
    def test_list_empty(self, client):
        r = client.get("/activities/")
        assert r.status_code == 200
        assert r.json() == []

    def test_list_returns_records(self, client, sample_activity):
        r = client.get("/activities/")
        assert r.status_code == 200
        assert len(r.json()) == 1

    def test_filter_by_type(self, client, sample_activity, sample_ride):
        r = client.get("/activities/?type=Run")
        assert len(r.json()) == 1
        assert r.json()[0]["type"] == "Run"

        r = client.get("/activities/?type=Ride")
        assert len(r.json()) == 1
        assert r.json()[0]["type"] == "Ride"

    def test_filter_by_date_range(self, client, sample_activity, sample_ride):
        # Both in range
        r = client.get("/activities/?date_from=2024-06-01&date_to=2024-06-30")
        assert len(r.json()) == 2

        # Only the run
        r = client.get("/activities/?date_from=2024-06-15&date_to=2024-06-15")
        assert len(r.json()) == 1
        assert r.json()[0]["type"] == "Run"

        # None in range
        r = client.get("/activities/?date_from=2025-01-01")
        assert len(r.json()) == 0

    def test_pagination(self, client, sample_activity, sample_ride):
        r = client.get("/activities/?limit=1")
        assert len(r.json()) == 1

        r = client.get("/activities/?skip=1&limit=1")
        assert len(r.json()) == 1

        r = client.get("/activities/?skip=2&limit=1")
        assert len(r.json()) == 0


# ===========================================================================
# GET /activities/{id}
# ===========================================================================

class TestGetActivity:
    def test_get_existing(self, client, sample_activity):
        r = client.get(f"/activities/{sample_activity.id}")
        assert r.status_code == 200
        assert r.json()["id"] == sample_activity.id

    def test_get_nonexistent_returns_404(self, client):
        r = client.get("/activities/99999")
        assert r.status_code == 404


# ===========================================================================
# PUT /activities/{id}
# ===========================================================================

class TestUpdateActivity:
    def test_partial_update(self, client, sample_activity):
        r = client.put(
            f"/activities/{sample_activity.id}",
            json={"temperature": 25.0, "humidity": 70.0},
        )
        assert r.status_code == 200
        assert r.json()["temperature"] == 25.0
        assert r.json()["humidity"] == 70.0
        # Unchanged fields should remain
        assert r.json()["distance_km"] == 10.5

    def test_update_nonexistent_returns_404(self, client):
        r = client.put("/activities/99999", json={"temperature": 20.0})
        assert r.status_code == 404


# ===========================================================================
# DELETE /activities/{id}
# ===========================================================================

class TestDeleteActivity:
    def test_delete_existing(self, client, sample_activity):
        r = client.delete(f"/activities/{sample_activity.id}")
        assert r.status_code == 204

        # Confirm it's gone
        r = client.get(f"/activities/{sample_activity.id}")
        assert r.status_code == 404

    def test_delete_nonexistent_returns_404(self, client):
        r = client.delete("/activities/99999")
        assert r.status_code == 404

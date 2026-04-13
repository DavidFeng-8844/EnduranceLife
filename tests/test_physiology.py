"""
tests/test_physiology.py — Tests for PhysiologyLog CRUD.

Coverage:
    - POST   /physiology/       (create + JSON zones)
    - GET    /physiology/       (list + pid filter)
    - GET    /physiology/{id}   (single + 404)
    - PUT    /physiology/{id}   (partial update)
    - DELETE /physiology/{id}   (delete + 404)
"""


# ===========================================================================
# POST /physiology/
# ===========================================================================

class TestCreatePhysiologyLog:
    def test_create_success(self, client):
        payload = {
            "pid": 1,
            "date": "2024-07-01",
            "height_cm": 177.0,
            "weight_kg": 65.0,
            "vo2max": 50.0,
            "resting_heart_rate": 55,
            "running_fitness": 42.0,
            "threshold_hr_zones": '{"z1":"94-122","z2":"122-139"}',
            "threshold_pace_zones": '{"z1":"6:30-7:15","z2":"5:39-6:30"}',
        }
        r = client.post("/physiology/", json=payload)
        assert r.status_code == 201
        data = r.json()
        assert data["vo2max"] == 50.0
        assert data["resting_heart_rate"] == 55
        assert "id" in data

    def test_create_minimal(self, client):
        """Only pid and date are truly needed."""
        payload = {"pid": 1, "date": "2024-08-01"}
        r = client.post("/physiology/", json=payload)
        assert r.status_code == 201
        assert r.json()["vo2max"] is None


# ===========================================================================
# GET /physiology/
# ===========================================================================

class TestListPhysiologyLogs:
    def test_list_empty(self, client):
        r = client.get("/physiology/")
        assert r.status_code == 200
        assert r.json() == []

    def test_list_with_data(self, client, sample_physiology_log):
        r = client.get("/physiology/")
        assert len(r.json()) == 1

    def test_filter_by_pid(self, client, sample_physiology_log):
        r = client.get("/physiology/?pid=1")
        assert len(r.json()) == 1
        r = client.get("/physiology/?pid=999")
        assert len(r.json()) == 0


# ===========================================================================
# GET /physiology/{id}
# ===========================================================================

class TestGetPhysiologyLog:
    def test_get_existing(self, client, sample_physiology_log):
        r = client.get(f"/physiology/{sample_physiology_log.id}")
        assert r.status_code == 200
        assert r.json()["vo2max"] == 52.0

    def test_get_nonexistent_returns_404(self, client):
        r = client.get("/physiology/99999")
        assert r.status_code == 404


# ===========================================================================
# PUT /physiology/{id}
# ===========================================================================

class TestUpdatePhysiologyLog:
    def test_partial_update(self, client, sample_physiology_log):
        r = client.put(
            f"/physiology/{sample_physiology_log.id}",
            json={"vo2max": 55.0, "weight_kg": 63.5},
        )
        assert r.status_code == 200
        assert r.json()["vo2max"] == 55.0
        assert r.json()["weight_kg"] == 63.5
        # Unchanged
        assert r.json()["resting_heart_rate"] == 55

    def test_update_nonexistent_returns_404(self, client):
        r = client.put("/physiology/99999", json={"vo2max": 50.0})
        assert r.status_code == 404


# ===========================================================================
# DELETE /physiology/{id}
# ===========================================================================

class TestDeletePhysiologyLog:
    def test_delete_existing(self, client, sample_physiology_log):
        r = client.delete(f"/physiology/{sample_physiology_log.id}")
        assert r.status_code == 204

        r = client.get(f"/physiology/{sample_physiology_log.id}")
        assert r.status_code == 404

    def test_delete_nonexistent_returns_404(self, client):
        r = client.delete("/physiology/99999")
        assert r.status_code == 404

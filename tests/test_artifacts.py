"""Tests for the Artifact catalog API."""

from fastapi.testclient import TestClient


def _create_task(client: TestClient) -> dict:
    resp = client.post(
        "/api/tasks/",
        json={"name": "Parent Task", "data_type": "DEM", "task_type": "process"},
    )
    assert resp.status_code == 201
    return resp.json()


def _create_artifact(client: TestClient, **overrides) -> dict:
    payload = {
        "name": "Test Artifact",
        "description": "An artifact",
        "file_path": "data/output.tif",
        "file_type": "GeoTIFF",
        "file_size": 1024,
        "crs": "EPSG:4326",
        "bounds": [-180.0, -90.0, 180.0, 90.0],
        "resolution": 30.0,
        "tags": ["elevation"],
        **overrides,
    }
    resp = client.post("/api/artifacts/", json=payload)
    assert resp.status_code == 201
    return resp.json()


# ---------------------------------------------------------------------------
# CRUD
# ---------------------------------------------------------------------------


class TestCreateArtifact:
    def test_create_basic(self, client):
        artifact = _create_artifact(client)
        assert artifact["id"] == 1
        assert artifact["name"] == "Test Artifact"
        assert artifact["file_type"] == "GeoTIFF"
        assert artifact["crs"] == "EPSG:4326"
        assert artifact["resolution"] == 30.0
        assert artifact["tags"] == ["elevation"]

    def test_create_all_file_types(self, client):
        for ft in ("GeoTIFF", "DEM", "PNG", "GeoJSON", "Shapefile", "CSV", "Other"):
            a = _create_artifact(client, name=f"art-{ft}", file_type=ft)
            assert a["file_type"] == ft

    def test_create_with_task(self, client):
        task = _create_task(client)
        artifact = _create_artifact(client, task_id=task["id"])
        assert artifact["task_id"] == task["id"]

    def test_create_with_invalid_task(self, client):
        resp = client.post(
            "/api/artifacts/",
            json={"name": "A", "file_path": "p.tif", "task_id": 9999},
        )
        assert resp.status_code == 404

    def test_invalid_file_type(self, client):
        resp = client.post(
            "/api/artifacts/",
            json={"name": "A", "file_path": "p.tif", "file_type": "INVALID"},
        )
        assert resp.status_code == 422

    def test_missing_file_path(self, client):
        resp = client.post("/api/artifacts/", json={"name": "A"})
        assert resp.status_code == 422

    def test_create_minimal(self, client):
        resp = client.post(
            "/api/artifacts/",
            json={"name": "Minimal", "file_path": "minimal.tif"},
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["crs"] is None
        assert data["bounds"] is None
        assert data["resolution"] is None
        assert data["tags"] == []


class TestListArtifacts:
    def test_empty_list(self, client):
        resp = client.get("/api/artifacts/")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_returns_all(self, client):
        _create_artifact(client, name="A1")
        _create_artifact(client, name="A2")
        assert len(client.get("/api/artifacts/").json()) == 2


class TestGetArtifact:
    def test_get_existing(self, client):
        artifact = _create_artifact(client)
        resp = client.get(f"/api/artifacts/{artifact['id']}")
        assert resp.status_code == 200
        assert resp.json()["id"] == artifact["id"]

    def test_get_not_found(self, client):
        resp = client.get("/api/artifacts/9999")
        assert resp.status_code == 404


class TestUpdateArtifact:
    def test_update_tags(self, client):
        artifact = _create_artifact(client)
        resp = client.put(
            f"/api/artifacts/{artifact['id']}",
            json={"tags": ["dem", "2024"]},
        )
        assert resp.status_code == 200
        assert resp.json()["tags"] == ["dem", "2024"]

    def test_update_crs(self, client):
        artifact = _create_artifact(client)
        resp = client.put(
            f"/api/artifacts/{artifact['id']}",
            json={"crs": "EPSG:3857"},
        )
        assert resp.status_code == 200
        assert resp.json()["crs"] == "EPSG:3857"

    def test_update_not_found(self, client):
        resp = client.put("/api/artifacts/9999", json={"crs": "EPSG:4326"})
        assert resp.status_code == 404


class TestDeleteArtifact:
    def test_delete_existing(self, client):
        artifact = _create_artifact(client)
        resp = client.delete(f"/api/artifacts/{artifact['id']}")
        assert resp.status_code == 204
        assert client.get(f"/api/artifacts/{artifact['id']}").status_code == 404

    def test_delete_not_found(self, client):
        resp = client.delete("/api/artifacts/9999")
        assert resp.status_code == 404


class TestListByTask:
    def test_list_by_task(self, client):
        task = _create_task(client)
        _create_artifact(client, task_id=task["id"], name="A1")
        _create_artifact(client, task_id=task["id"], name="A2")
        _create_artifact(client, name="A3")  # no task

        resp = client.get(f"/api/artifacts/task/{task['id']}")
        assert resp.status_code == 200
        assert len(resp.json()) == 2

    def test_list_by_missing_task(self, client):
        resp = client.get("/api/artifacts/task/9999")
        assert resp.status_code == 404

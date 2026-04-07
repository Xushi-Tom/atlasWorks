"""Tests for the Task management API."""

import pytest
from fastapi.testclient import TestClient


def _create_task(client: TestClient, **overrides) -> dict:
    payload = {
        "name": "Test Task",
        "description": "A test task",
        "data_type": "GeoTIFF",
        "task_type": "process",
        "input_files": ["dem.tif"],
        **overrides,
    }
    resp = client.post("/api/tasks/", json=payload)
    assert resp.status_code == 201
    return resp.json()


# ---------------------------------------------------------------------------
# CRUD
# ---------------------------------------------------------------------------


class TestCreateTask:
    def test_create_basic(self, client):
        task = _create_task(client)
        assert task["id"] == 1
        assert task["name"] == "Test Task"
        assert task["status"] == "pending"
        assert task["progress"] == 0
        assert task["input_files"] == ["dem.tif"]

    def test_create_all_data_types(self, client):
        for dt in ("GeoTIFF", "DEM", "Other"):
            task = _create_task(client, name=f"task-{dt}", data_type=dt)
            assert task["data_type"] == dt

    def test_create_all_task_types(self, client):
        for tt in ("process", "convert", "analyze", "tile"):
            task = _create_task(client, name=f"task-{tt}", task_type=tt)
            assert task["task_type"] == tt

    def test_invalid_data_type(self, client):
        resp = client.post(
            "/api/tasks/",
            json={"name": "bad", "data_type": "INVALID", "task_type": "process"},
        )
        assert resp.status_code == 422

    def test_invalid_task_type(self, client):
        resp = client.post(
            "/api/tasks/",
            json={"name": "bad", "data_type": "DEM", "task_type": "INVALID"},
        )
        assert resp.status_code == 422

    def test_missing_name(self, client):
        resp = client.post("/api/tasks/", json={"data_type": "DEM"})
        assert resp.status_code == 422


class TestListTasks:
    def test_empty_list(self, client):
        resp = client.get("/api/tasks/")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_returns_all_tasks(self, client):
        _create_task(client, name="T1")
        _create_task(client, name="T2")
        resp = client.get("/api/tasks/")
        assert len(resp.json()) == 2


class TestGetTask:
    def test_get_existing(self, client):
        task = _create_task(client)
        resp = client.get(f"/api/tasks/{task['id']}")
        assert resp.status_code == 200
        assert resp.json()["id"] == task["id"]

    def test_get_not_found(self, client):
        resp = client.get("/api/tasks/9999")
        assert resp.status_code == 404


class TestUpdateTask:
    def test_update_name(self, client):
        task = _create_task(client)
        resp = client.put(
            f"/api/tasks/{task['id']}",
            json={"name": "Updated Name"},
        )
        assert resp.status_code == 200
        assert resp.json()["name"] == "Updated Name"

    def test_update_not_found(self, client):
        resp = client.put("/api/tasks/9999", json={"name": "X"})
        assert resp.status_code == 404

    def test_partial_update(self, client):
        task = _create_task(client, description="original")
        resp = client.put(
            f"/api/tasks/{task['id']}",
            json={"description": "updated desc"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["description"] == "updated desc"
        assert data["name"] == "Test Task"  # unchanged


class TestDeleteTask:
    def test_delete_existing(self, client):
        task = _create_task(client)
        resp = client.delete(f"/api/tasks/{task['id']}")
        assert resp.status_code == 204
        assert client.get(f"/api/tasks/{task['id']}").status_code == 404

    def test_delete_not_found(self, client):
        resp = client.delete("/api/tasks/9999")
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Run endpoint
# ---------------------------------------------------------------------------


class TestRunTask:
    def test_run_pending_task(self, client):
        task = _create_task(client)
        resp = client.post(f"/api/tasks/{task['id']}/run")
        assert resp.status_code == 200

    def test_run_creates_artifact(self, client):
        task = _create_task(client)
        client.post(f"/api/tasks/{task['id']}/run")
        artifacts_resp = client.get(f"/api/artifacts/task/{task['id']}")
        assert artifacts_resp.status_code == 200
        # Background task runs synchronously in TestClient
        artifacts = artifacts_resp.json()
        assert len(artifacts) >= 1

    def test_run_completed_task_fails(self, client):
        task = _create_task(client)
        client.post(f"/api/tasks/{task['id']}/run")
        # After run the task is completed
        state = client.get(f"/api/tasks/{task['id']}").json()
        if state["status"] == "completed":
            resp = client.post(f"/api/tasks/{task['id']}/run")
            assert resp.status_code == 400

    def test_run_not_found(self, client):
        resp = client.post("/api/tasks/9999/run")
        assert resp.status_code == 404

    def test_run_sets_task_completed(self, client):
        task = _create_task(client)
        client.post(f"/api/tasks/{task['id']}/run")
        state = client.get(f"/api/tasks/{task['id']}").json()
        assert state["status"] == "completed"
        assert state["progress"] == 100

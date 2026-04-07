"""Tests for the Publishing API."""

from fastapi.testclient import TestClient


def _create_artifact(client: TestClient, name: str = "Art") -> dict:
    resp = client.post(
        "/api/artifacts/",
        json={"name": name, "file_path": "data/out.tif", "file_type": "GeoTIFF"},
    )
    assert resp.status_code == 201
    return resp.json()


def _create_publication(client: TestClient, artifact_id: int, **overrides) -> dict:
    payload = {
        "name": "My Publication",
        "description": "Test publication",
        "artifact_id": artifact_id,
        "publish_type": "static",
        "endpoint_path": "/data/my-layer",
        "access_level": "public",
        **overrides,
    }
    resp = client.post("/api/publish/", json=payload)
    assert resp.status_code == 201
    return resp.json()


# ---------------------------------------------------------------------------
# CRUD
# ---------------------------------------------------------------------------


class TestCreatePublication:
    def test_create_basic(self, client):
        artifact = _create_artifact(client)
        pub = _create_publication(client, artifact["id"])
        assert pub["id"] == 1
        assert pub["status"] == "active"
        assert pub["access_level"] == "public"
        assert pub["artifact_id"] == artifact["id"]

    def test_create_all_publish_types(self, client):
        artifact = _create_artifact(client)
        for i, pt in enumerate(("tiles", "static", "wms", "api")):
            pub = _create_publication(
                client,
                artifact["id"],
                publish_type=pt,
                endpoint_path=f"/layer/{i}",
            )
            assert pub["publish_type"] == pt

    def test_duplicate_endpoint_rejected(self, client):
        artifact = _create_artifact(client)
        _create_publication(client, artifact["id"], endpoint_path="/shared")
        resp = client.post(
            "/api/publish/",
            json={
                "name": "Dup",
                "artifact_id": artifact["id"],
                "publish_type": "static",
                "endpoint_path": "/shared",
                "access_level": "public",
            },
        )
        assert resp.status_code == 400

    def test_inactive_endpoint_can_be_reused(self, client):
        artifact = _create_artifact(client)
        pub = _create_publication(client, artifact["id"], endpoint_path="/reuse")
        # Deactivate it
        client.post(f"/api/publish/{pub['id']}/toggle")
        # Now the same path should be allowed
        resp = client.post(
            "/api/publish/",
            json={
                "name": "Reuse",
                "artifact_id": artifact["id"],
                "publish_type": "static",
                "endpoint_path": "/reuse",
                "access_level": "public",
            },
        )
        assert resp.status_code == 201

    def test_create_with_missing_artifact(self, client):
        resp = client.post(
            "/api/publish/",
            json={
                "name": "Bad",
                "artifact_id": 9999,
                "publish_type": "static",
                "endpoint_path": "/nowhere",
                "access_level": "public",
            },
        )
        assert resp.status_code == 404

    def test_invalid_publish_type(self, client):
        artifact = _create_artifact(client)
        resp = client.post(
            "/api/publish/",
            json={
                "name": "Bad",
                "artifact_id": artifact["id"],
                "publish_type": "invalid",
                "endpoint_path": "/x",
                "access_level": "public",
            },
        )
        assert resp.status_code == 422

    def test_invalid_access_level(self, client):
        artifact = _create_artifact(client)
        resp = client.post(
            "/api/publish/",
            json={
                "name": "Bad",
                "artifact_id": artifact["id"],
                "publish_type": "static",
                "endpoint_path": "/x",
                "access_level": "restricted",
            },
        )
        assert resp.status_code == 422


class TestListPublications:
    def test_empty_list(self, client):
        resp = client.get("/api/publish/")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_returns_all(self, client):
        artifact = _create_artifact(client)
        _create_publication(client, artifact["id"], endpoint_path="/a")
        _create_publication(client, artifact["id"], endpoint_path="/b")
        assert len(client.get("/api/publish/").json()) == 2


class TestGetPublication:
    def test_get_existing(self, client):
        artifact = _create_artifact(client)
        pub = _create_publication(client, artifact["id"])
        resp = client.get(f"/api/publish/{pub['id']}")
        assert resp.status_code == 200
        assert resp.json()["id"] == pub["id"]

    def test_get_not_found(self, client):
        resp = client.get("/api/publish/9999")
        assert resp.status_code == 404


class TestUpdatePublication:
    def test_update_name(self, client):
        artifact = _create_artifact(client)
        pub = _create_publication(client, artifact["id"])
        resp = client.put(
            f"/api/publish/{pub['id']}",
            json={"name": "Updated"},
        )
        assert resp.status_code == 200
        assert resp.json()["name"] == "Updated"

    def test_update_endpoint_path(self, client):
        artifact = _create_artifact(client)
        pub = _create_publication(client, artifact["id"], endpoint_path="/old")
        resp = client.put(
            f"/api/publish/{pub['id']}",
            json={"endpoint_path": "/new"},
        )
        assert resp.status_code == 200
        assert resp.json()["endpoint_path"] == "/new"

    def test_update_endpoint_conflict(self, client):
        artifact = _create_artifact(client)
        _create_publication(client, artifact["id"], endpoint_path="/taken")
        pub2 = _create_publication(client, artifact["id"], endpoint_path="/free")
        resp = client.put(
            f"/api/publish/{pub2['id']}",
            json={"endpoint_path": "/taken"},
        )
        assert resp.status_code == 400

    def test_update_not_found(self, client):
        resp = client.put("/api/publish/9999", json={"name": "X"})
        assert resp.status_code == 404


class TestDeletePublication:
    def test_delete_existing(self, client):
        artifact = _create_artifact(client)
        pub = _create_publication(client, artifact["id"])
        resp = client.delete(f"/api/publish/{pub['id']}")
        assert resp.status_code == 204
        assert client.get(f"/api/publish/{pub['id']}").status_code == 404

    def test_delete_not_found(self, client):
        resp = client.delete("/api/publish/9999")
        assert resp.status_code == 404


class TestTogglePublication:
    def test_toggle_active_to_inactive(self, client):
        artifact = _create_artifact(client)
        pub = _create_publication(client, artifact["id"])
        assert pub["status"] == "active"
        resp = client.post(f"/api/publish/{pub['id']}/toggle")
        assert resp.status_code == 200
        assert resp.json()["status"] == "inactive"

    def test_toggle_inactive_to_active(self, client):
        artifact = _create_artifact(client)
        pub = _create_publication(client, artifact["id"])
        client.post(f"/api/publish/{pub['id']}/toggle")  # -> inactive
        resp = client.post(f"/api/publish/{pub['id']}/toggle")  # -> active
        assert resp.json()["status"] == "active"

    def test_toggle_not_found(self, client):
        resp = client.post("/api/publish/9999/toggle")
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Cascade delete
# ---------------------------------------------------------------------------


class TestCascadeDelete:
    def test_delete_artifact_removes_publication(self, client):
        artifact = _create_artifact(client)
        pub = _create_publication(client, artifact["id"])
        # Deleting the artifact should also remove the publication
        client.delete(f"/api/artifacts/{artifact['id']}")
        resp = client.get(f"/api/publish/{pub['id']}")
        assert resp.status_code == 404

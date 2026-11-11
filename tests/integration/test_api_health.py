"""Integration tests: health endpoint."""


def test_health_returns_ok(client):
    response = client.get("/api/health")
    assert response.status_code == 200
    body = response.get_json()
    assert body["status"] == "ok"
    assert body["app"] == "cheiloscan"
    assert body["version"]
    assert body["database"] == {"connected": True, "schema_version": 2}


def test_health_reports_dependency_versions(client):
    body = client.get("/api/health").get_json()
    dependencies = body["dependencies"]
    assert set(dependencies) == {"flask", "sqlalchemy"}
    for name, version in dependencies.items():
        assert isinstance(version, str) and version
        assert version != "not-installed"


def test_health_reports_database_failure(client, app, tmp_path):
    from cheiloscan.db.session import Database

    broken = Database(
        "sqlite:///" + (tmp_path / "missing-dir" / "x.db").as_posix()
    )
    try:
        original = app.extensions["database"]
        app.extensions["database"] = broken
        response = client.get("/api/health")
        assert response.status_code == 503
        body = response.get_json()
        assert body["status"] == "error"
        assert body["database"]["connected"] is False
    finally:
        broken.dispose()
        app.extensions["database"] = original


def test_health_does_not_leak_filesystem_paths(client):
    body = client.get("/api/health").get_json()
    serialized = str(body)
    assert "storage_path" not in serialized
    assert "sqlite:" not in serialized
    assert "data_dir" not in serialized.lower()

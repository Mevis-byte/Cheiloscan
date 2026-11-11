"""Integration tests: samples listing endpoint."""

from __future__ import annotations

from cheiloscan.db.models import ImageAsset
from cheiloscan.db.repositories import (
    AnalysisRepository,
    SampleRepository,
)


def _seed(database, count: int = 3) -> list[str]:
    with database.session() as session:
        repository = SampleRepository(session)
        for index in range(count):
            repository.create(code=f"S-{index:03d}", research_notes=f"note {index}")
    return [f"S-{index:03d}" for index in range(count)]


def test_samples_list_empty(client):
    response = client.get("/api/samples")
    assert response.status_code == 200
    body = response.get_json()
    assert body == {"items": [], "total": 0, "limit": 50, "offset": 0}


def test_samples_list_returns_records(client, database):
    _seed(database, count=3)
    body = client.get("/api/samples").get_json()

    assert body["total"] == 3
    assert [sample["code"] for sample in body["items"]] == [
        "S-000",
        "S-001",
        "S-002",
    ]
    sample = body["items"][0]
    assert set(sample) == {
        "id",
        "code",
        "research_notes",
        "capture_type",
        "medium",
        "collection_method",
        "donor_ref",
        "consent_confirmed",
        "captured_at",
        "created_at",
        "updated_at",
        "deleted_at",
        "image_count",
        "analyses_count",
        "images",
    }
    assert sample["research_notes"] == "note 0"
    assert sample["consent_confirmed"] is False
    assert sample["created_at"].endswith("Z")


def test_samples_pagination(client, database):
    _seed(database, count=3)
    body = client.get("/api/samples?limit=1&offset=1").get_json()
    assert body["total"] == 3
    assert [sample["code"] for sample in body["items"]] == ["S-001"]


def test_samples_pagination_validation(client):
    for query in ("limit=0", "limit=9999", "limit=-1", "limit=abc", "offset=-4", "offset=no"):
        response = client.get(f"/api/samples?{query}")
        assert response.status_code == 400, query
        assert response.get_json()["error"]["code"] == "bad_request"


def test_samples_soft_deleted_hidden_by_default(client, database):
    codes = _seed(database, count=2)
    with database.session() as session:
        repository = SampleRepository(session)
        repository.soft_delete(repository.get_by_code(codes[0]).id)

    body = client.get("/api/samples").get_json()
    assert body["total"] == 1
    assert body["items"][0]["code"] == codes[1]
    assert body["items"][0]["deleted_at"] is None

    included = client.get("/api/samples?include_deleted=true").get_json()
    assert included["total"] == 2
    deleted = [s for s in included["items"] if s["code"] == codes[0]]
    assert deleted and deleted[0]["deleted_at"] is not None


def test_samples_include_image_metadata_and_counts(client, database):
    with database.session() as session:
        repository = SampleRepository(session)
        sample = repository.create(code="S-with-image", consent_confirmed=True)
        session.add(
            ImageAsset(
                sample_id=sample.id,
                sha256="d" * 64,
                storage_path="original/dd/x.png",
                format="png",
                width=32,
                height=24,
                size_bytes=512,
            )
        )
        AnalysisRepository(session).create(
            sample_id=sample.id, pipeline_name="p", pipeline_version="1"
        )

    body = client.get("/api/samples").get_json()
    item = body["items"][0]
    assert item["image_count"] == 1
    assert item["analyses_count"] == 1
    assert item["consent_confirmed"] is True
    image = item["images"][0]
    assert image["sha256"] == "d" * 64
    assert image["width"] == 32 and image["height"] == 24
    assert image["kind"] == "original"


def test_samples_response_never_exposes_storage_paths(client, database):
    _seed(database, count=1)
    with database.session() as session:
        repository = SampleRepository(session)
        sample = repository.get_by_code("S-000")
        session.add(
            ImageAsset(
                sample_id=sample.id,
                sha256="e" * 64,
                storage_path="original/ee/secret-relative-path.png",
                format="png",
                width=1,
                height=1,
                size_bytes=1,
            )
        )

    raw = client.get("/api/samples").get_data(as_text=True)
    assert "storage_path" not in raw
    assert "secret-relative-path" not in raw

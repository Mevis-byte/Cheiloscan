"""Integration tests: comparisons listing endpoint."""

from __future__ import annotations

from cheiloscan.db.repositories import ComparisonRepository, SampleRepository


def _seed_pair(database) -> tuple[str, str]:
    with database.session() as session:
        repository = SampleRepository(session)
        sample_a = repository.create(code="CMP-A")
        sample_b = repository.create(code="CMP-B")
        return sample_a.id, sample_b.id


def test_comparisons_list_empty(client):
    response = client.get("/api/comparisons")
    assert response.status_code == 200
    assert response.get_json() == {
        "items": [],
        "total": 0,
        "limit": 50,
        "offset": 0,
    }


def test_comparisons_list_returns_records(client, database):
    sample_a, sample_b = _seed_pair(database)
    with database.session() as session:
        ComparisonRepository(session).create(
            sample_a_id=sample_a,
            sample_b_id=sample_b,
            method="heuristic_fusion_v1",
            method_version="1",
            status="pending",
        )

    body = client.get("/api/comparisons").get_json()
    assert body["total"] == 1
    item = body["items"][0]
    assert set(item) == {
        "id",
        "method",
        "method_version",
        "status",
        "params",
        "component_scores",
        "fused_score",
        "error",
        "created_at",
        "finished_at",
        "sample_a",
        "sample_b",
    }
    assert item["method"] == "heuristic_fusion_v1"
    assert item["status"] == "pending"
    assert item["sample_a"]["code"] == "CMP-A"
    assert item["sample_b"]["code"] == "CMP-B"
    assert item["component_scores"] is None  # engine arrives in Phase 7
    assert item["fused_score"] is None


def test_comparisons_pagination(client, database):
    codes = []
    with database.session() as session:
        samples = SampleRepository(session)
        for index in range(4):
            codes.append(samples.create(code=f"CP-{index}").id)
        comparisons = ComparisonRepository(session)
        for index in range(3):
            comparisons.create(
                sample_a_id=codes[0],
                sample_b_id=codes[index + 1],
                method="m",
            )

    page_one = client.get("/api/comparisons?limit=2").get_json()
    assert page_one["total"] == 3 and len(page_one["items"]) == 2
    page_two = client.get("/api/comparisons?limit=2&offset=2").get_json()
    assert page_two["total"] == 3 and len(page_two["items"]) == 1

    all_items = client.get("/api/comparisons?limit=50").get_json()["items"]
    pairs = [(item["sample_a"]["code"], item["sample_b"]["code"]) for item in all_items]
    assert ("CP-0", "CP-3") in pairs

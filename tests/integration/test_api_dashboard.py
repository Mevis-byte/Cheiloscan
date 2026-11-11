"""Integration tests: dashboard statistics endpoint."""

from __future__ import annotations

from cheiloscan.db.repositories import (
    AnalysisRepository,
    ComparisonRepository,
    SampleRepository,
)


def test_dashboard_stats_empty_database_is_honestly_zero(client):
    response = client.get("/api/dashboard/stats")
    assert response.status_code == 200
    body = response.get_json()

    assert body["samples"] == {"total": 0, "active": 0}
    assert body["images"] == {"total": 0}
    assert body["analyses"] == {"total": 0, "by_status": {}}
    assert body["comparisons"] == {"total": 0, "by_status": {}}
    assert body["storage"]["bytes"] >= 0  # db file exists: nonzero in practice
    assert body["database"]["schema_version"] == 1
    assert body["generated_at"].endswith("Z")


def test_dashboard_stats_counts_real_records(client, database):
    with database.session() as session:
        samples = SampleRepository(session)
        sample_a = samples.create(code="DASH-A")
        sample_b = samples.create(code="DASH-B")

        analyses = AnalysisRepository(session)
        analyses.create(
            sample_id=sample_a.id,
            pipeline_name="baseline",
            pipeline_version="1",
            status="succeeded",
        )
        analyses.create(
            sample_id=sample_a.id,
            pipeline_name="baseline",
            pipeline_version="1",
            status="failed",
        )
        analyses.create(
            sample_id=sample_b.id,
            pipeline_name="baseline",
            pipeline_version="1",
            status="pending",
        )

        comparisons = ComparisonRepository(session)
        comparisons.create(
            sample_a_id=sample_a.id, sample_b_id=sample_b.id, method="m"
        )

    body = client.get("/api/dashboard/stats").get_json()
    assert body["samples"] == {"total": 2, "active": 2}
    assert body["images"] == {"total": 0}
    assert body["analyses"] == {
        "total": 3,
        "by_status": {"succeeded": 1, "failed": 1, "pending": 1},
    }
    assert body["comparisons"] == {"total": 1, "by_status": {"pending": 1}}


def test_dashboard_stats_excludes_soft_deleted_samples(client, database):
    with database.session() as session:
        repository = SampleRepository(session)
        sample = repository.create(code="DASH-DEL")
        repository.create(code="DASH-KEEP")
        repository.soft_delete(sample.id)

    body = client.get("/api/dashboard/stats").get_json()
    assert body["samples"] == {"total": 2, "active": 1}


def test_dashboard_stats_contains_no_matching_metrics(client):
    """The claim policy forbids accuracy/matching metrics without data."""
    body = client.get("/api/dashboard/stats").get_json()
    serialized = str(body).lower()
    for forbidden in ("accuracy", "match_rate", "far", "frr", "eer", "score"):
        assert forbidden not in serialized

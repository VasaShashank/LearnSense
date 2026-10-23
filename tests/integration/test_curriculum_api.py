"""
Curriculum & knowledge-graph HTTP API (Person 2).

These tests drive the real mounted routes (``/api/curriculum/...``) through
FastAPI's TestClient against the real ``backend.app``.  The ``get_service``
dependency is overridden to construct a *fresh* service per request over one
tmp-dir repository, so every read below proves the previous request actually
persisted -- and the shared ``storage/`` tree is never written to.

Status-code contract under test:

* ``200``  reads reflect only persisted state (an unseeded install answers
  empty lists, never sample data);
* ``400``  a spec the domain schema rejects inside the seed handler;
* ``404``  unknown concept / relationship / version id;
* ``409``  domain conflicts: an unseedable graph, a snapshot before any seed, a
  review decision aimed at something that does not exist;
* ``422``  a request body missing required fields (FastAPI/pydantic, never
  reaching the handler).
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from backend.app import app
from backend.routes.curriculum import get_service
from backend.services.curriculum_service import CurriculumService
from curriculum.repository import CurriculumRepository

#: Minimal four-concept spec: a prerequisite chain (Position -> Velocity ->
#: Acceleration) plus Momentum depending on Velocity, so every concept is
#: reachable and the graph seeds with zero warnings.
API_SPEC = {
    "curriculum_id": "api_test_v1",
    "syllabus_version": "2026.api.v1",
    "title": "API integration slice",
    "concepts": [
        {
            "stable_key": "physics/kinematics/position",
            "name": "Position",
            "subject": "physics",
            "aliases": ["location"],
            "prerequisites": [],
        },
        {
            "stable_key": "physics/kinematics/velocity",
            "name": "Velocity",
            "subject": "physics",
            "prerequisites": ["physics/kinematics/position"],
        },
        {
            "stable_key": "physics/kinematics/acceleration",
            "name": "Acceleration",
            "subject": "physics",
            "prerequisites": ["physics/kinematics/velocity"],
        },
        {
            "stable_key": "physics/kinematics/momentum",
            "name": "Momentum",
            "subject": "physics",
            "prerequisites": ["physics/kinematics/velocity"],
        },
    ],
    "relationships": [
        {
            "source_key": "physics/kinematics/position",
            "target_key": "physics/kinematics/velocity",
            "type": "prerequisite_of",
        },
        {
            "source_key": "physics/kinematics/velocity",
            "target_key": "physics/kinematics/acceleration",
            "type": "prerequisite_of",
        },
    ],
}

#: A prerequisite cycle: valid spec shape, unseedable graph -> 409.
CYCLE_SPEC = {
    "curriculum_id": "api_cycle_v1",
    "concepts": [
        {"stable_key": "physics/kinematics/alpha", "name": "Alpha", "subject": "physics"},
        {"stable_key": "physics/kinematics/beta", "name": "Beta", "subject": "physics"},
    ],
    "relationships": [
        {
            "source_key": "physics/kinematics/alpha",
            "target_key": "physics/kinematics/beta",
            "type": "prerequisite_of",
        },
        {
            "source_key": "physics/kinematics/beta",
            "target_key": "physics/kinematics/alpha",
            "type": "prerequisite_of",
        },
    ],
}

#: References a stable key that no concept declares -> 409 before any graph work.
GHOST_PREREQ_SPEC = {
    "curriculum_id": "api_ghost_v1",
    "concepts": [
        {
            "stable_key": "physics/kinematics/lonely",
            "name": "Lonely",
            "subject": "physics",
            "prerequisites": ["physics/kinematics/ghost"],
        }
    ],
}


@pytest.fixture
def repo(tmp_path):
    """Repository rooted in tmp so the suite never touches ``storage/``."""
    return CurriculumRepository(base_dir=str(tmp_path / "curriculum_store"))


@pytest.fixture
def client(repo):
    """The real app; every request builds a fresh service over the tmp repo."""
    app.dependency_overrides[get_service] = lambda: CurriculumService(repository=repo)
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.pop(get_service, None)


@pytest.fixture
def seed_body(client):
    response = client.post(
        "/api/curriculum/seed",
        json={"spec": API_SPEC, "reviewer_id": "api_teacher"},
    )
    assert response.status_code == 200, response.text
    return response.json()


def concept_ids_by_name(client):
    response = client.get("/api/curriculum/concepts")
    assert response.status_code == 200
    return {item["name"]: item["concept_id"] for item in response.json()["concepts"]}


class TestUnseededState:
    def test_reads_report_empty_state_and_never_sample_data(self, client):
        status = client.get("/api/curriculum/status").json()
        assert status["has_curriculum"] is False
        assert status["concept_count"] == 0
        assert status["relationship_count"] == 0
        assert status["versions"] == 0
        assert status["pending_review"] == 0

        listing = client.get("/api/curriculum").json()
        assert listing["curricula"] == []

        concepts = client.get("/api/curriculum/concepts").json()
        assert concepts["has_curriculum"] is False
        assert concepts["count"] == 0
        assert concepts["concepts"] == []

        assert client.get("/api/curriculum/contract").json()["count"] == 0
        assert client.get("/api/curriculum/versions").json()["count"] == 0
        assert client.get("/api/curriculum/review/records").json()["count"] == 0

    @pytest.mark.parametrize(
        "path",
        [
            "/api/curriculum/concepts/cc_missing",
            "/api/curriculum/concepts/cc_missing/prerequisites",
            "/api/curriculum/relationships/rel_missing",
        ],
    )
    def test_unknown_ids_are_404_with_the_id_in_the_detail(self, client, path):
        response = client.get(path)
        assert response.status_code == 404
        assert "missing" in response.json()["detail"]

    def test_snapshot_before_any_seed_is_409(self, client):
        response = client.post("/api/curriculum/versions", json={"created_by": "teacher"})
        assert response.status_code == 409
        assert "Seed a curriculum first" in response.json()["detail"]


class TestSeedEndpoint:
    def test_seed_response_contract(self, client, seed_body):
        fingerprint = seed_body.pop("fingerprint")
        assert seed_body == {
            "curriculum_id": "api_test_v1",
            "concept_count": 4,
            "relationship_count": 3,  # 3 unique edges, declared twice in the spec
            "is_valid": True,
            "warnings": 0,
        }
        assert isinstance(fingerprint, str) and fingerprint

    def test_state_is_visible_to_the_next_fresh_request(self, client, seed_body):
        status = client.get("/api/curriculum/status").json()
        assert status["has_curriculum"] is True
        assert status["curriculum_id"] == "api_test_v1"
        assert status["concept_count"] == 4
        assert status["relationship_count"] == 3
        assert status["is_valid"] is True
        assert status["fingerprint"] == seed_body["fingerprint"]

        listing = client.get("/api/curriculum").json()
        assert listing == {"curricula": ["api_test_v1"], "active": "api_test_v1"}

        records = client.get("/api/curriculum/review/records").json()
        assert records["count"] == 4
        assert {r["action"] for r in records["records"]} == {"accept_concept"}
        assert {r["reviewer_role"] for r in records["records"]} == {"system"}
        assert {r["reviewer_id"] for r in records["records"]} == {"api_teacher"}

    @pytest.mark.parametrize(
        "spec",
        [
            {"curriculum_id": "x", "concepts": "nope"},
            {"curriculum_id": "x", "concepts": [], "bogus_field": 1},
        ],
    )
    def test_malformed_spec_is_400_not_500(self, client, spec):
        response = client.post("/api/curriculum/seed", json={"spec": spec})
        assert response.status_code == 400
        assert response.json()["detail"].startswith("Invalid curriculum spec:")

    @pytest.mark.parametrize(
        "spec, expected_fragment",
        [
            (CYCLE_SPEC, "Seeded curriculum graph is invalid"),
            (GHOST_PREREQ_SPEC, "unknown prerequisite key"),
        ],
    )
    def test_unseedable_spec_is_409_with_the_reason(self, client, spec, expected_fragment):
        response = client.post("/api/curriculum/seed", json={"spec": spec})
        assert response.status_code == 409
        assert expected_fragment in response.json()["detail"]

    def test_request_body_missing_the_spec_is_422(self, client):
        response = client.post("/api/curriculum/seed", json={"reviewer_id": "x"})
        assert response.status_code == 422


class TestSeededReads:
    def test_concept_listing_filters_and_pagination(self, client, seed_body):
        base = client.get("/api/curriculum/concepts").json()
        assert base["count"] == 4
        assert base["offset"] == 0

        assert client.get("/api/curriculum/concepts?subject=physics").json()["count"] == 4
        assert client.get("/api/curriculum/concepts?subject=chemistry").json()["count"] == 0
        assert client.get("/api/curriculum/concepts?status=active").json()["count"] == 4

        hits = client.get("/api/curriculum/concepts?q=Velocity").json()
        assert [c["name"] for c in hits["concepts"]] == ["Velocity"]

        page = client.get("/api/curriculum/concepts?limit=2&offset=2").json()
        assert page["count"] == 2
        assert page["offset"] == 2

    def test_concept_detail_shows_the_neighborhood(self, client, seed_body):
        ids = concept_ids_by_name(client)
        detail = client.get(f"/api/curriculum/concepts/{ids['Velocity']}").json()

        assert detail["concept_id"] == ids["Velocity"]
        assert detail["resolved_from"] is None
        assert detail["successors"] == []
        assert [p["name"] for p in detail["prerequisites"]] == ["Position"]
        assert {"Acceleration", "Momentum"} <= {d["name"] for d in detail["dependents"]}
        assert detail["prerequisite_count"] == 1
        assert detail["contract"]["concept_id"] == ids["Velocity"]

    def test_learning_order_respects_every_prerequisite(self, client, seed_body):
        ids = concept_ids_by_name(client)
        body = client.get("/api/curriculum/learning-order").json()

        assert body["count"] == 4
        order = body["order"]
        assert set(order) == set(ids.values())
        assert order.index(ids["Position"]) < order.index(ids["Velocity"])
        assert order.index(ids["Velocity"]) < order.index(ids["Acceleration"])
        assert order.index(ids["Velocity"]) < order.index(ids["Momentum"])

    def test_validate_status_and_contract_agree(self, client, seed_body):
        report = client.post("/api/curriculum/validate").json()
        assert report["is_valid"] is True
        assert report["error_count"] == 0
        assert report["warning_count"] == 0

        status = client.get("/api/curriculum/status").json()
        assert status["is_valid"] is True
        assert status["error_count"] == 0
        assert status["warning_count"] == 0

        contract = client.get("/api/curriculum/contract").json()
        assert contract["count"] == 4
        required = {"concept_id", "name", "description", "status"}
        assert all(required <= set(record) for record in contract["concepts"])
        assert len({frozenset(record) for record in contract["concepts"]}) == 1

    def test_relationship_listing_and_filters(self, client, seed_body):
        body = client.get("/api/curriculum/relationships").json()
        assert body["count"] == 3
        assert {r["type"] for r in body["relationships"]} == {"prerequisite_of"}
        assert {r["status"] for r in body["relationships"]} == {"accepted"}

        filtered = client.get(
            "/api/curriculum/relationships?relationship_type=prerequisite_of&status=accepted"
        ).json()
        assert filtered["count"] == 3
        assert client.get("/api/curriculum/relationships?relationship_type=part_of").json()[
            "count"
        ] == 0

    def test_provenance_trace_is_scoped_to_the_subject(self, client, seed_body):
        velocity_id = concept_ids_by_name(client)["Velocity"]
        chain = client.get(f"/api/curriculum/provenance/{velocity_id}").json()
        assert chain["subject_id"] == velocity_id
        assert chain["count"] >= 1
        assert all(record["subject_id"] == velocity_id for record in chain["chain"])

        absent = client.get("/api/curriculum/provenance/cc_absent").json()
        assert absent == {"subject_id": "cc_absent", "count": 0, "chain": []}

    def test_mapping_reads_start_empty(self, client, seed_body):
        assert client.get("/api/curriculum/mapping/runs").json() == {"count": 0, "runs": []}
        assert client.get("/api/curriculum/mapping/pending").json() == {
            "count": 0,
            "pending": [],
        }


class TestReviewConflicts:
    def test_deprecate_unknown_concept_is_409(self, client, seed_body):
        response = client.post(
            "/api/curriculum/review/deprecate",
            json={"concept_id": "cc_nope", "reviewer_id": "api_teacher", "reason": "not real"},
        )
        assert response.status_code == 409
        assert "does not exist" in response.json()["detail"]

    def test_merge_onto_unknown_target_is_409(self, client, seed_body):
        response = client.post(
            "/api/curriculum/review/merge",
            json={"keep_id": "cc_nope", "merge_ids": ["cc_other"], "reviewer_id": "api_teacher"},
        )
        assert response.status_code == 409
        assert "Merge target" in response.json()["detail"]

    def test_relationship_status_for_unknown_id_is_409(self, client, seed_body):
        response = client.post(
            "/api/curriculum/review/relationships/rel_nope/status",
            json={"status": "rejected", "reviewer_id": "api_teacher"},
        )
        assert response.status_code == 409
        assert "does not exist" in response.json()["detail"]

    def test_missing_required_review_field_is_422(self, client, seed_body):
        response = client.post(
            "/api/curriculum/review/deprecate",
            json={"concept_id": "cc_something", "reviewer_id": "api_teacher"},
        )
        assert response.status_code == 422  # reason is required; handler never runs


class TestReviewMutationVisibility:
    def test_deprecate_hides_a_concept_and_records_the_decision(self, client, seed_body):
        velocity_id = concept_ids_by_name(client)["Velocity"]
        response = client.post(
            "/api/curriculum/review/deprecate",
            json={
                "concept_id": velocity_id,
                "reviewer_id": "api_teacher",
                "reason": "definition superseded",
            },
        )
        assert response.status_code == 200, response.text
        assert response.json()["status"] == "deprecated"

        visible = client.get("/api/curriculum/concepts").json()
        assert visible["count"] == 3
        assert velocity_id not in {c["concept_id"] for c in visible["concepts"]}

        everything = client.get("/api/curriculum/concepts?include_deprecated=true").json()
        assert everything["count"] == 4

        deprecated = client.get(
            "/api/curriculum/concepts?include_deprecated=true&status=deprecated"
        ).json()
        assert [c["concept_id"] for c in deprecated["concepts"]] == [velocity_id]

        status = client.get("/api/curriculum/status").json()
        assert status["concept_count"] == 4  # still in the graph; only listings hide it
        assert status["is_valid"] is True

        records = client.get("/api/curriculum/review/records").json()
        assert records["count"] == 5
        # Both the seeded accept and the deprecate decision carry the concept
        # as their subject; the deprecate one is the non-accept action.
        decisions = [r for r in records["records"] if r["subject_id"] == velocity_id]
        assert len(decisions) == 2
        assert sum(1 for r in decisions if r["action"] == "accept_concept") == 1
        deprecations = [r for r in decisions if r["action"] != "accept_concept"]
        assert len(deprecations) == 1
        assert deprecations[0]["reviewer_id"] == "api_teacher"


class TestVersioningEndpoints:
    def test_snapshot_diff_and_content_addressed_ids(self, client, seed_body):
        first = client.post(
            "/api/curriculum/versions",
            json={"created_by": "api_teacher", "note": "baseline"},
        )
        assert first.status_code == 200, first.text
        v1 = first.json()
        assert v1["content_checksum"] == seed_body["fingerprint"]
        assert v1["concept_count"] == 4

        listed = client.get("/api/curriculum/versions").json()
        assert listed["count"] == 1
        assert listed["versions"][0]["version_id"] == v1["version_id"]

        # Mutate the graph so the next snapshot has different content.
        momentum_id = concept_ids_by_name(client)["Momentum"]
        deprecated = client.post(
            "/api/curriculum/review/deprecate",
            json={
                "concept_id": momentum_id,
                "reviewer_id": "api_teacher",
                "reason": "curriculum change",
            },
        )
        assert deprecated.status_code == 200, deprecated.text

        v2 = client.post(
            "/api/curriculum/versions",
            json={"created_by": "api_teacher", "note": "after deprecation"},
        ).json()
        assert v2["version_id"] != v1["version_id"]
        assert v2["content_checksum"] != v1["content_checksum"]

        diff = client.get(
            f"/api/curriculum/versions/diff?from={v1['version_id']}&to={v2['version_id']}"
        )
        assert diff.status_code == 200, diff.text
        body = diff.json()
        assert body["concepts_modified"] == [momentum_id]
        assert body["concepts_added"] == []
        assert body["concepts_removed"] == []
        assert body["concepts_renamed"] == {}
        # Deprecating without a successor still records an id_map tombstone
        # (relation "deprecated", old_id == current_id), so the diff reports it.
        assert body["id_map_added"] == [momentum_id]
        assert body["relationship_count_delta"] == 0
        assert body["fingerprint_changed"] is True

        # Content-addressed ids: re-snapshotting identical content reuses the id
        # instead of inventing a duplicate version.
        repeated = client.post(
            "/api/curriculum/versions",
            json={"created_by": "someone_else", "note": "again"},
        ).json()
        assert repeated["version_id"] == v2["version_id"]
        assert client.get("/api/curriculum/versions").json()["count"] == 2

    def test_diff_with_unknown_version_is_404(self, client, seed_body):
        created = client.post(
            "/api/curriculum/versions", json={"created_by": "api_teacher"}
        ).json()
        response = client.get(
            f"/api/curriculum/versions/diff?from=cv_missing&to={created['version_id']}"
        )
        assert response.status_code == 404
        assert "cv_missing" in response.json()["detail"]


class TestReadinessAndCompatibilityEndpoints:
    def test_compatibility_unseeded(self, client):
        res = client.get("/api/curriculum/compatibility")
        assert res.status_code == 200
        body = res.json()
        assert body["has_curriculum"] is False
        assert body["status"] == "UNSEEDED"

    def test_compatibility_seeded(self, client, seed_body):
        res = client.get("/api/curriculum/compatibility")
        assert res.status_code == 200
        body = res.json()
        assert body["status"] == "COMPATIBLE FOR TESTING"
        assert body["concept_count"] == 4
        assert body["relationship_count"] == 3
        assert body["adapter_contract_satisfied"] is True
        assert body["release_gate"] == "COMPATIBLE FOR TESTING"

    def test_readiness_evaluation(self, client, seed_body):
        concepts = client.get("/api/curriculum/concepts").json()["concepts"]
        by_name = {c["name"]: c["concept_id"] for c in concepts}
        pos_id = by_name["Position"]
        vel_id = by_name["Velocity"]

        # Root concept (Position) is always ready with no prerequisites
        res_root = client.post(
            f"/api/curriculum/concepts/{pos_id}/readiness",
            json={"mastery_map": {}, "threshold": 0.50},
        )
        assert res_root.status_code == 200
        assert res_root.json()["is_ready"] is True
        assert res_root.json()["remediation_needed"] == []

        # Velocity requires Position >= 0.50
        # 1. Unsatisfied: Position at 0.30
        res_unready = client.post(
            f"/api/curriculum/concepts/{vel_id}/readiness",
            json={"mastery_map": {pos_id: 0.30}, "threshold": 0.50},
        )
        assert res_unready.status_code == 200
        body_unready = res_unready.json()
        assert body_unready["is_ready"] is False
        assert pos_id in body_unready["remediation_needed"]
        assert body_unready["prerequisite_status_map"][pos_id] == "unsatisfied"

        # 2. Satisfied: Position at 0.85
        res_ready = client.post(
            f"/api/curriculum/concepts/{vel_id}/readiness",
            json={"mastery_map": {pos_id: 0.85}, "threshold": 0.50},
        )
        assert res_ready.status_code == 200
        body_ready = res_ready.json()
        assert body_ready["is_ready"] is True
        assert body_ready["remediation_needed"] == []
        assert body_ready["prerequisite_status_map"][pos_id] == "satisfied"

    def test_readiness_unknown_concept_is_404(self, client, seed_body):
        res = client.post(
            "/api/curriculum/concepts/cc_missing/readiness",
            json={"mastery_map": {}, "threshold": 0.50},
        )
        assert res.status_code == 404


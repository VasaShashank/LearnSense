"""
Unit tests for Person 2:
1. P1 Conics resolution & prerequisite direction.
2. P1 Optics umbrella deprecation & sequential chain.
3. Concept metadata update (PUT /concepts/{id}).
4. Curriculum publishing gate & release freeze (POST /publish).
5. Safe version rollback (POST /versions/{id}/rollback).
"""

from __future__ import annotations

import json
from pathlib import Path
import pytest
from fastapi.testclient import TestClient

from backend.app import app
from backend.routes.curriculum import get_service
from backend.services.curriculum_service import CurriculumService
from curriculum.models import ConceptLifecycleStatus
from curriculum.repository import CurriculumRepository
from curriculum.seed import load_spec, seed_curriculum


@pytest.fixture
def isolated_env(tmp_path):
    repo = CurriculumRepository(base_dir=str(tmp_path / "curriculum"))
    spec = load_spec("curriculum/data/jee_curriculum_spec.json")
    seed_curriculum(spec, repository=repo)
    service = CurriculumService(repository=repo)

    app.dependency_overrides[get_service] = lambda: service
    try:
        yield service
    finally:
        app.dependency_overrides.pop(get_service, None)


class TestP1AcademicRemediation:
    """Verify academic corrections for Conics and Optics."""

    def test_p1_conics_direction_and_resolution(self, isolated_env):
        service = isolated_env
        graph = service.get_graph()

        conics_placeholder = graph.concepts.get("cc_566dd708e45bdf97")
        assert conics_placeholder is not None
        assert conics_placeholder.status == ConceptLifecycleStatus.DEPRECATED

        # Historical lookup resolves to canonical Conic Sections
        resolved = graph.resolve_id("cc_566dd708e45bdf97")
        assert resolved == "cc_3d26d1722cc57f40"

        # Invalid prerequisite Conics -> Straight Lines does not exist
        for r in graph.relationships.values():
            assert not (r.source == "cc_566dd708e45bdf97" and r.target == "cc_7d5698538e81c82d"), (
                "Found inverted relationship: Conics -> Straight Lines!"
            )

        # Pedagogical progression: Straight Lines -> Circles -> Conic Sections
        straight_lines = graph.concepts["cc_7d5698538e81c82d"]
        circles = graph.concepts["cc_97ca5374e03783c5"]
        conic_sections = graph.concepts["cc_3d26d1722cc57f40"]

        assert "cc_7d5698538e81c82d" in circles.prerequisite_concept_ids
        assert "cc_97ca5374e03783c5" in conic_sections.prerequisite_concept_ids

        # Crosswalk mapping for basic coordinates mapped to Straight Lines
        items = service.list_syllabus_items()
        u10_01 = next(item for item in items if item["syllabus_item_id"] == "syl_math_u10_01")
        assert "cc_7d5698538e81c82d" in u10_01["canonical_concept_ids"]

    def test_p1_optics_umbrella_and_resolution(self, isolated_env):
        service = isolated_env
        graph = service.get_graph()

        umbrella = graph.concepts.get("cc_a0f8c26d421e9c83")
        assert umbrella is not None
        assert umbrella.status == ConceptLifecycleStatus.DEPRECATED

        # Bogus edge Kinematics -> Ray & Wave Optics removed
        for r in graph.relationships.values():
            assert not (r.source == "cc_3e003bf9b038a36b" and r.target == "cc_a0f8c26d421e9c83"), (
                "Found bogus relationship: Kinematics -> Ray and Wave Optics!"
            )

        # Genuine optics progression: Waves -> Ray Optics -> Wave Optics
        ray_optics = graph.concepts["cc_d70ece71bc616b7b"]
        wave_optics = graph.concepts["cc_3c10e1bef7c6bb38"]

        assert "cc_45e6d2763944e1d4" in ray_optics.prerequisite_concept_ids  # Waves
        assert "cc_d70ece71bc616b7b" in wave_optics.prerequisite_concept_ids  # Ray Optics

        # Crosswalk mappings
        items = service.list_syllabus_items()
        u16_01 = next(item for item in items if item["syllabus_item_id"] == "syl_phy_u16_01")
        u16_02 = next(item for item in items if item["syllabus_item_id"] == "syl_phy_u16_02")
        assert "cc_d70ece71bc616b7b" in u16_01["canonical_concept_ids"]
        assert "cc_3c10e1bef7c6bb38" in u16_02["canonical_concept_ids"]


class TestTeacherWorkflowExtensions:
    """Verify concept metadata editing, publishing, and rollback."""

    def test_update_concept_metadata_api(self, isolated_env):
        client = TestClient(app)

        update_payload = {
            "name": "Updated Permutations and Combinations",
            "description": "Fundamental counting principles, permutations and combinations.",
            "aliases": ["P and C", "Counting Principles"],
            "tags": ["math", "algebra", "updated"],
            "reviewer_id": "test_senior_teacher",
            "note": "Refined syllabus description and aliases",
        }
        res = client.put("/api/curriculum/concepts/cc_6c289cbb2834295f", json=update_payload)
        assert res.status_code == 200
        data = res.json()
        assert data["name"] == "Updated Permutations and Combinations"
        assert "P and C" in data["aliases"]
        assert data["audit"]["updated_by"] == "test_senior_teacher"

    def test_publish_and_rollback_curriculum_api(self, isolated_env):
        client = TestClient(app)

        # 1. Publish current curriculum
        pub_res = client.post("/api/curriculum/publish", json={
            "reviewer_id": "lead_auditor",
            "release_notes": "Official release candidate 2026.jee.v1",
        })
        assert pub_res.status_code == 200
        pub_data = pub_res.json()
        assert pub_data["status"] == "published"
        version_id = pub_data["version_id"]
        assert version_id.startswith("cv_")

        # 2. Mutate a concept
        client.put("/api/curriculum/concepts/cc_6c289cbb2834295f", json={
            "name": "Mutated Name Before Rollback",
            "reviewer_id": "someone",
        })
        get_res = client.get("/api/curriculum/concepts/cc_6c289cbb2834295f")
        assert get_res.json()["name"] == "Mutated Name Before Rollback"

        # 3. Rollback to published snapshot
        rollback_res = client.post(f"/api/curriculum/versions/{version_id}/rollback", json={
            "reviewer_id": "lead_auditor",
            "note": "Reverting test mutation",
        })
        assert rollback_res.status_code == 200
        rb_data = rollback_res.json()
        assert rb_data["status"] == "rolled_back"

        # 4. Verify concept was restored
        restored_res = client.get("/api/curriculum/concepts/cc_6c289cbb2834295f")
        assert restored_res.json()["name"] != "Mutated Name Before Rollback"

    def test_publish_gate_refuses_invalid_graph(self, isolated_env):
        service = isolated_env
        graph = service.get_graph()

        # Artificially corrupt graph by introducing a cycle
        from curriculum.models import ConceptRelationship
        from phase2.models import RelationshipStatusEnum, RelationshipTypeEnum
        # Add reverse edge creating cycle: Circles -> Straight Lines
        bad_rel = ConceptRelationship.create(
            "cc_97ca5374e03783c5",
            RelationshipTypeEnum.PREREQUISITE_OF,
            "cc_7d5698538e81c82d",
            status=RelationshipStatusEnum.ACCEPTED,
        )
        graph.add_relationship(bad_rel)
        graph.concepts["cc_7d5698538e81c82d"].add_prerequisite("cc_97ca5374e03783c5")
        service.repository.save_graph(graph)

        # Attempt to publish must be refused with ValueError
        with pytest.raises(ValueError, match="Cannot publish invalid curriculum"):
            service.publish_curriculum(reviewer_id="lead_auditor")

"""
Unit and integration tests for the Learning Path Explorer & Guided Sequence API.

Verifies:
1. Chapter-coherent progression sequence generation.
2. User-selected starting concept scoping (Step 1 = Starting Concept).
3. Upstream prerequisite ancestor identification (with direct vs indirect tagging).
4. Reachable downstream DAG traversal and parallel branch detection.
5. Cross-chapter bridge detection with pedagogical explanations.
6. Single primary recommendation guarantee (prevents duplicate Next Best Step cards).
7. Resilience against invalid concept IDs and missing subjects.
8. FastAPI route HTTP contract via TestClient.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from backend.app import app
from backend.services.knowledge_service import KnowledgeService
from phase3.errors import KnowledgeNotFoundError

LAWS_OF_MOTION_DOC_ID = (
    "doc_121418-jee-main-2023-24-laws-of-motion-revision-notes-free-pdf-download"
)


class TestLearningSequenceExplorer:
    @pytest.fixture(autouse=True)
    def setup_service(self):
        self.ks = KnowledgeService()
        self.client = TestClient(app)

    def test_default_sequence_full_curriculum_coverage(self):
        """Default sequence should cover all concepts in chapter-coherent order."""
        res = self.ks.get_learning_sequence(LAWS_OF_MOTION_DOC_ID)

        assert res["subject_id"] == LAWS_OF_MOTION_DOC_ID
        assert res["starting_concept_id"] is None
        assert res["starting_concept_name"] is None
        assert len(res["upstream_prerequisites"]) == 0

        sequence = res["sequence"]
        assert len(sequence) == 14, f"Expected 14 concepts, got {len(sequence)}"

        # Step numbering must be sequential 1..N
        for idx, item in enumerate(sequence, start=1):
            assert item["step_number"] == idx
            assert item["step_label"] == f"Step {idx}"
            assert item["name"]
            assert item["chapter_name"]
            assert item["reason"]

        # Exactly 1 primary recommendation
        assert res["primary_recommendation"] is not None
        assert "concept_id" in res["primary_recommendation"]
        assert "name" in res["primary_recommendation"]

    def test_cross_chapter_bridges_detected(self):
        """Cross-chapter bridges connecting Newton's Laws, Friction, and Centripetal Motion must be identified."""
        res = self.ks.get_learning_sequence(LAWS_OF_MOTION_DOC_ID)
        bridges = res["cross_chapter_bridges"]
        assert len(bridges) >= 2, f"Expected at least 2 cross-chapter bridges, got {len(bridges)}"

        bridge_pairs = [(b["source_name"].lower(), b["target_name"].lower()) for b in bridges]

        # Verify Second Law -> Static Friction
        assert any("second law" in s and "static friction" in t for s, t in bridge_pairs)

        # Verify Second Law -> Centripetal Acceleration or Friction -> Centripetal Acceleration
        assert any("centripetal acceleration" in t for s, t in bridge_pairs)

        for b in bridges:
            assert b["source_chapter"] != b["target_chapter"], "Bridge must cross chapters"
            assert b["explanation"], "Pedagogical explanation must be provided"

    def test_parallel_branch_detection(self):
        """Parallel branches sharing the same prerequisite (e.g. Centripetal and Tangential Accel) must be detected."""
        res = self.ks.get_learning_sequence(LAWS_OF_MOTION_DOC_ID)
        branches = res["branching_points"]
        assert len(branches) > 0

        # Angular Velocity branches into Centripetal Acceleration & Tangential Acceleration
        ang_branch = next((b for b in branches if "angular velocity" in b["parent_name"].lower()), None)
        assert ang_branch is not None, "Angular velocity branch not detected"
        branch_names = [sub["name"].lower() for sub in ang_branch["branches"]]
        assert any("centripetal acceleration" in name for name in branch_names)
        assert any("tangential acceleration" in name for name in branch_names)

    def test_starting_from_root_concept(self):
        """Starting from Newton's First Law should have 0 upstream prerequisites and make it Step 1."""
        graph = self.ks.get_subject_graph(LAWS_OF_MOTION_DOC_ID)
        first_law = next(c for c in graph["concepts"] if "first law" in c["name"].lower())
        first_law_id = first_law["concept_id"]

        res = self.ks.get_learning_sequence(LAWS_OF_MOTION_DOC_ID, starting_concept_id=first_law_id)

        assert res["starting_concept_id"] == first_law_id
        assert "first law" in res["starting_concept_name"].lower()
        assert len(res["upstream_prerequisites"]) == 0

        sequence = res["sequence"]
        assert sequence[0]["concept_id"] == first_law_id
        assert sequence[0]["step_number"] == 1
        assert sequence[0]["is_starting_concept"] is True

    def test_starting_from_intermediate_concept(self):
        """Starting from Static Friction must correctly gather upstream prerequisites (Second Law, Net Force, First Law)."""
        graph = self.ks.get_subject_graph(LAWS_OF_MOTION_DOC_ID)
        static_fric = next(c for c in graph["concepts"] if c["name"].lower() == "static friction")
        static_fric_id = static_fric["concept_id"]

        res = self.ks.get_learning_sequence(LAWS_OF_MOTION_DOC_ID, starting_concept_id=static_fric_id)

        assert res["starting_concept_id"] == static_fric_id
        assert res["sequence"][0]["concept_id"] == static_fric_id
        assert res["sequence"][0]["step_number"] == 1

        upstream = res["upstream_prerequisites"]
        assert len(upstream) >= 1
        upstream_names = [u["name"].lower() for u in upstream]
        assert any("second law" in name for name in upstream_names)

        # Check direct vs indirect tagging
        direct_prereqs = [u for u in upstream if u["is_direct"]]
        assert any("second law" in u["name"].lower() for u in direct_prereqs)

    def test_starting_from_tangential_acceleration(self):
        """Starting from Tangential Acceleration scopes path down to Net Acceleration in Circular Motion."""
        graph = self.ks.get_subject_graph(LAWS_OF_MOTION_DOC_ID)
        tangential = next(c for c in graph["concepts"] if "tangential acceleration" in c["name"].lower())
        tang_id = tangential["concept_id"]

        res = self.ks.get_learning_sequence(LAWS_OF_MOTION_DOC_ID, starting_concept_id=tang_id)

        assert res["starting_concept_id"] == tang_id
        assert res["sequence"][0]["concept_id"] == tang_id
        assert res["sequence"][0]["step_number"] == 1

        # Upstream must be Angular Velocity
        upstream = res["upstream_prerequisites"]
        assert any("angular velocity" in u["name"].lower() for u in upstream)

        # Downstream reachable from Tangential Acceleration must include Net Acceleration
        downstream_names = [item["name"].lower() for item in res["sequence"]]
        assert any("net acceleration" in name for name in downstream_names)

    def test_invalid_concept_id_graceful_fallback(self):
        """An invalid starting concept ID must fall back gracefully to the full curriculum sequence without error."""
        res = self.ks.get_learning_sequence(LAWS_OF_MOTION_DOC_ID, starting_concept_id="non_existent_c_9999")
        assert res["starting_concept_id"] is None
        assert len(res["sequence"]) == 14

    def test_empty_or_missing_subject_raises_not_found(self):
        """A non-existent subject should raise KnowledgeNotFoundError, and API should return 404."""
        with pytest.raises(KnowledgeNotFoundError):
            self.ks.get_learning_sequence("doc_non_existent_999")

        response = self.client.get("/api/subjects/doc_non_existent_999/learning-sequence")
        assert response.status_code == 404

    def test_api_route_contract(self):
        """FastAPI route /api/subjects/{subject_id}/learning-sequence returns valid payload."""
        response = self.client.get(f"/api/subjects/{LAWS_OF_MOTION_DOC_ID}/learning-sequence")
        assert response.status_code == 200
        data = response.json()
        assert "subject_id" in data
        assert "sequence" in data
        assert "cross_chapter_bridges" in data
        assert "branching_points" in data
        assert "primary_recommendation" in data
        assert len(data["sequence"]) == 14

    def test_api_route_with_starting_concept(self):
        """FastAPI route with ?starting_concept_id= scopes the sequence."""
        graph = self.ks.get_subject_graph(LAWS_OF_MOTION_DOC_ID)
        static_fric = next(c for c in graph["concepts"] if c["name"].lower() == "static friction")
        cid = static_fric["concept_id"]

        response = self.client.get(
            f"/api/subjects/{LAWS_OF_MOTION_DOC_ID}/learning-sequence",
            params={"starting_concept_id": cid},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["starting_concept_id"] == cid
        assert data["sequence"][0]["concept_id"] == cid
        assert len(data["upstream_prerequisites"]) > 0

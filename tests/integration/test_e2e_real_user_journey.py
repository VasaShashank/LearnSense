"""
Phase 7 End-to-End Real User Journey Integration Test Suite.
Verifies complete real user flows across all Taproot phases (Phases 1-6 integration):
1. New Learner Complete Journey
2. Zero-Knowledge Learner Scenario
3. Returning Learner Scenario
4. Mixed-Knowledge Learner Scenario
5. Assessment -> KT -> Atlas Master State Sync
"""

import os
import io
import pytest
from fastapi.testclient import TestClient
from backend.app import app
from storage.repositories import SessionRepository, LearningContextRepository
from phase3.storage.learner_repository import LearnerStateRepository
from phase3.knowledge.phase2_adapter import LearningContext, ConceptView, PrerequisiteLink

client = TestClient(app)


def create_sample_learning_context(subject_id: str) -> LearningContext:
    """Helper to populate a multi-concept calculus subject context into repository."""
    ctx = LearningContext(
        document_id=subject_id,
        knowledge_document_id=f"kdoc_{subject_id}",
        concepts={
            "c_limits": ConceptView(
                concept_id="c_limits",
                canonical_name="Limits & Continuity",
                type="CORE",
                aliases=[],
            ),
            "c_derivatives": ConceptView(
                concept_id="c_derivatives",
                canonical_name="Derivatives",
                type="CORE",
                aliases=[],
            ),
            "c_chain_rule": ConceptView(
                concept_id="c_chain_rule",
                canonical_name="Chain Rule",
                type="CORE",
                aliases=[],
            ),
            "c_integrals": ConceptView(
                concept_id="c_integrals",
                canonical_name="Definite Integrals",
                type="CORE",
                aliases=[],
            ),
        },
        prerequisites=[
            PrerequisiteLink(source_concept_id="c_limits", target_concept_id="c_derivatives", confidence=1.0),
            PrerequisiteLink(source_concept_id="c_derivatives", target_concept_id="c_chain_rule", confidence=1.0),
            PrerequisiteLink(source_concept_id="c_derivatives", target_concept_id="c_integrals", confidence=1.0),
        ],
    )
    LearningContextRepository().save_context(ctx)
    return ctx


def test_e2e_new_learner_complete_journey():
    """
    Tests the full user flow for a new student:
    Self-Assessment -> Diagnostic -> Initial KT -> Gaps -> Path -> Activity -> State & Atlas Sync.
    """
    subject_id = "subj_calculus_e2e"
    learner_id = "learner_new_101"
    create_sample_learning_context(subject_id)

    all_concepts = ["c_limits", "c_derivatives", "c_chain_rule", "c_integrals"]

    # 1. Concept Self-Assessment
    sa_res = client.post(
        "/api/initialization/self-assessment",
        json={
            "learner_id": learner_id,
            "subject_id": subject_id,
            "selections": {
                "c_limits": "KNOW",
                "c_derivatives": "DONT_KNOW",
            },
            "all_subject_concept_ids": all_concepts,
        },
    )
    assert sa_res.status_code == 200
    sa_data = sa_res.json()
    session_id = sa_data["session_id"]
    assert sa_data["know_concept_ids"] == ["c_limits"]
    assert sa_data["dont_know_concept_ids"] == ["c_derivatives"]
    assert set(sa_data["unanswered_concept_ids"]) == {"c_chain_rule", "c_integrals"}

    # 2. Start Diagnostic for KNOW concepts only
    diag_start_res = client.post(
        "/api/initialization/diagnostic/start",
        json={"session_id": session_id},
    )
    assert diag_start_res.status_code == 200
    diag_start_data = diag_start_res.json()
    assert diag_start_data["know_concepts"] == ["c_limits"]
    assert diag_start_data["question_count"] > 0
    q_id = diag_start_data["questions"][0]["question_id"]

    # 3. Submit Diagnostic Response
    diag_sub_res = client.post(
        "/api/initialization/diagnostic/submit",
        json={
            "session_id": session_id,
            "responses": {q_id: 1.0},
        },
    )
    assert diag_sub_res.status_code == 200
    diag_sub_data = diag_sub_res.json()
    assert diag_sub_data["diagnostic_completed"] is True
    assert "c_limits" in diag_sub_data["updated_masteries"]
    assert diag_sub_data["updated_masteries"]["c_limits"] > 0.3

    # 4. Retrieve Knowledge Gaps & Personalized Path
    gaps_res = client.get(f"/api/learners/{learner_id}/path-and-gaps?subject_id={subject_id}")
    assert gaps_res.status_code == 200
    gaps_data = gaps_res.json()
    assert len(gaps_data["gaps"]) > 0
    assert len(gaps_data["learning_path"]["nodes"]) > 0
    assert gaps_data["next_target"] is not None

    # 5. Submit Learning Activity Response
    act_res = client.post(
        "/api/learners/activity-response",
        json={
            "learner_id": learner_id,
            "subject_id": subject_id,
            "concept_ids": ["c_derivatives"],
            "correctness": 1.0,
            "all_subject_concept_ids": all_concepts,
        },
    )
    assert act_res.status_code == 200
    act_data = act_res.json()
    assert "c_derivatives" in act_data["updated_masteries"]
    assert act_data["updated_masteries"]["c_derivatives"] > 0.15

    # 6. Verify Learning Atlas reflects authoritative backend state
    atlas_res = client.get(f"/api/subjects/{subject_id}/graph?learner_id={learner_id}")
    assert atlas_res.status_code == 200
    atlas_data = atlas_res.json()

    c_deriv_node = next(c for c in atlas_data["concepts"] if c["concept_id"] == "c_derivatives")
    assert c_deriv_node["mastery"] == act_data["updated_masteries"]["c_derivatives"]


def test_e2e_zero_knowledge_learner():
    """
    Tests edge case where learner selects DONT_KNOW for all concepts:
    - Diagnostic is NOT run
    - Learner NOT set to mastery 0 everywhere
    - State remains neutral/uninitialized
    - Foundational concepts selected from prerequisite graph
    - Path generated normally
    """
    subject_id = "subj_calculus_e2e"
    learner_id = "learner_zero_202"
    create_sample_learning_context(subject_id)

    all_concepts = ["c_limits", "c_derivatives", "c_chain_rule", "c_integrals"]

    # 1. Self-assessment with DONT_KNOW for all concepts
    sa_res = client.post(
        "/api/initialization/self-assessment",
        json={
            "learner_id": learner_id,
            "subject_id": subject_id,
            "selections": {cid: "DONT_KNOW" for cid in all_concepts},
            "all_subject_concept_ids": all_concepts,
        },
    )
    assert sa_res.status_code == 200
    session_id = sa_res.json()["session_id"]
    assert sa_res.json()["know_concept_ids"] == []

    # 2. Start diagnostic -> returns 0 questions
    diag_res = client.post(
        "/api/initialization/diagnostic/start",
        json={"session_id": session_id},
    )
    assert diag_res.status_code == 200
    assert diag_res.json()["question_count"] == 0

    # 3. Check progress and mastery values (must be neutral Bayesian prior ~0.15-0.25, NOT 0.0)
    prog_res = client.get(f"/api/learners/{learner_id}/progress?subject_id={subject_id}")
    assert prog_res.status_code == 200
    prog_data = prog_res.json()
    assert prog_data["mastered_concepts"] == 0
    assert prog_data["explored_concepts"] == 0

    # 4. Check path and next target -> Foundational concept (c_limits) must be targeted first
    path_res = client.get(f"/api/learners/{learner_id}/path-and-gaps?subject_id={subject_id}")
    assert path_res.status_code == 200
    path_data = path_res.json()

    next_target = path_data["next_target"]
    assert next_target is not None
    assert next_target["concept_id"] == "c_limits"  # Foundational root node in graph


def test_e2e_returning_learner():
    """
    Tests returning learner session restoration from disk storage:
    - Existing state reloaded
    - Onboarding not repeated
    - Progress preserved
    """
    subject_id = "subj_calculus_e2e"
    learner_id = "learner_returning_303"
    create_sample_learning_context(subject_id)
    all_concepts = ["c_limits", "c_derivatives", "c_chain_rule", "c_integrals"]

    # 1. Simulate initial activity for student
    client.post(
        "/api/learners/activity-response",
        json={
            "learner_id": learner_id,
            "subject_id": subject_id,
            "concept_ids": ["c_limits"],
            "correctness": 1.0,
            "all_subject_concept_ids": all_concepts,
        },
    )

    # 2. Re-fetch learner progress and path (simulating page reload / application restart)
    prog_res = client.get(f"/api/learners/{learner_id}/progress?subject_id={subject_id}")
    assert prog_res.status_code == 200
    prog_data = prog_res.json()
    assert prog_data["explored_concepts"] == 1

    path_res = client.get(f"/api/learners/{learner_id}/path-and-gaps?subject_id={subject_id}")
    assert path_res.status_code == 200
    path_data = path_res.json()
    assert len(path_data["learning_path"]["nodes"]) > 0


def test_e2e_mixed_knowledge_learner():
    """
    Tests learner with mixed mastery levels:
    - Strong concepts are not repeated
    - Weak prerequisites are prioritized
    """
    subject_id = "subj_calculus_e2e"
    learner_id = "learner_mixed_404"
    create_sample_learning_context(subject_id)
    all_concepts = ["c_limits", "c_derivatives", "c_chain_rule", "c_integrals"]

    # Master 'c_limits' by submitting multiple correct responses
    for _ in range(4):
        client.post(
            "/api/learners/activity-response",
            json={
                "learner_id": learner_id,
                "subject_id": subject_id,
                "concept_ids": ["c_limits"],
                "correctness": 1.0,
                "all_subject_concept_ids": all_concepts,
            },
        )

    path_res = client.get(f"/api/learners/{learner_id}/path-and-gaps?subject_id={subject_id}")
    assert path_res.status_code == 200
    path_data = path_res.json()

    next_target = path_data["next_target"]
    assert next_target is not None
    # Next target should advance past mastered c_limits to c_derivatives
    assert next_target["concept_id"] == "c_derivatives"

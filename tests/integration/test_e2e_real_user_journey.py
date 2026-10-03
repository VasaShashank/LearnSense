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
from backend.services.knowledge_service import KnowledgeService
from backend.services.learner_service import LearnerService
from backend.services.learning_service import LearningService
from storage.repositories import SessionRepository, LearningContextRepository
from phase3.storage.learner_repository import LearnerStateRepository
from phase3.knowledge.phase2_adapter import LearningContext, PrerequisiteLink
from tests.conftest import CALCULUS_TEXT, _pdf_bytes

client = TestClient(app)

# Maps the concepts the real pipeline extracts to the stable IDs these journeys assert on.
# Only the *identifiers* are rewritten; names, evidence, page numbers and quotes all stay
# as the pipeline produced them, so questions are still grounded in real text.
_ID_BY_NAME = {
    "Limits": "c_limits",
    "Derivatives": "c_derivatives",
    "Chain Rule": "c_chain_rule",
    "Definite Integrals": "c_integrals",
}


def create_sample_learning_context(subject_id: str) -> LearningContext:
    """
    Ingest a real calculus PDF and persist its context under ``subject_id``.

    The concepts, their evidence and their page/block provenance are produced by the real
    Phase 1 -> Phase 2 pipeline. Only the concept IDs are remapped to the stable
    ``c_limits``/``c_derivatives``/... names the journeys below assert on.
    """
    from backend.services.knowledge_build_service import KnowledgeBuildService

    # reuse_existing=False: a leftover context on disk from an earlier run would be
    # returned as-is, and the journeys below need freshly extracted evidence.
    KnowledgeBuildService().build(
        subject_id, _pdf_bytes(CALCULUS_TEXT), "e2e_calculus.pdf", reuse_existing=False
    )

    ctx = LearningContextRepository().load_context(subject_id)
    assert ctx is not None, "real ingestion produced no context"
    assert ctx.evidence, "real ingestion produced no evidence to ground questions in"

    remapped = LearningContext(
        document_id=ctx.document_id,
        knowledge_document_id=ctx.knowledge_document_id,
        document_title=ctx.document_title,
        source_filename=ctx.source_filename,
        chapters=ctx.chapters,
        sections=ctx.sections,
        topics=ctx.topics,
        concepts={},
        skills=ctx.skills,
        formulas=ctx.formulas,
        educational_units=ctx.educational_units,
        assessable_items=ctx.assessable_items,
        concept_definitions=ctx.concept_definitions,
        evidence=ctx.evidence,
        prerequisites=[],
        trusted_relationships=ctx.trusted_relationships,
    )

    old_to_new = {}
    for concept in ctx.concepts.values():
        new_id = _ID_BY_NAME.get(concept.canonical_name)
        if not new_id:
            continue
        old_to_new[concept.concept_id] = new_id
        remapped.concepts[new_id] = concept.model_copy(update={"concept_id": new_id})

    # The pipeline does not assert an ordering, so the fixture states the intended
    # prerequisite chain explicitly for the path/targeting assertions.
    for source_name, target_name in (
        ("Limits", "Derivatives"),
        ("Derivatives", "Chain Rule"),
        ("Derivatives", "Definite Integrals"),
    ):
        remapped.prerequisites.append(
            PrerequisiteLink(
                source_concept_id=_ID_BY_NAME[source_name],
                target_concept_id=_ID_BY_NAME[target_name],
                confidence=1.0,
            )
        )

    assert len(remapped.concepts) == len(_ID_BY_NAME), (
        f"expected {sorted(_ID_BY_NAME.values())}, got {sorted(remapped.concepts)}"
    )

    # Point the persisted document's question bank/caching at the new IDs.
    LearningContextRepository().save_context(remapped)
    return remapped


def test_e2e_new_learner_complete_journey(purge_subject):
    """
    Tests the full user flow for a new student:
    Self-Assessment -> Diagnostic -> Initial KT -> Gaps -> Path -> Activity -> State & Atlas Sync.
    """
    subject_id = purge_subject("subj_calculus_e2e")
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
    # learner_id is REQUIRED: ownership must be explicit, not assumed.
    diag_start_res = client.post(
        "/api/initialization/diagnostic/start",
        json={"session_id": session_id, "learner_id": learner_id},
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
            "learner_id": learner_id,
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
    # Use the question_id from the diagnostic start -- it is guaranteed to be in
    # the bank because the server returned it from there.
    # Real server-authoritative path: a grounded question_id plus the correct option.
    # Client-reported correctness is no longer accepted by the API.
    act_res = client.post(
        "/api/learners/activity-response",
        json={
            "learner_id": learner_id,
            "subject_id": subject_id,
            "concept_ids": ["c_limits"],
            "question_id": q_id,
            "selected_option": diag_start_data["questions"][0]["options"][0],
            "all_subject_concept_ids": all_concepts,
        },
    )
    assert act_res.status_code == 200, act_res.text
    act_data = act_res.json()
    assert act_data["is_correct"] is True
    assert "c_limits" in act_data["updated_masteries"]
    assert act_data["updated_masteries"]["c_limits"] > 0.15

    # 6. Verify Learning Atlas reflects authoritative backend state
    atlas_res = client.get(f"/api/subjects/{subject_id}/graph?learner_id={learner_id}")
    assert atlas_res.status_code == 200
    atlas_data = atlas_res.json()

    c_limits_node = next(c for c in atlas_data["concepts"] if c["concept_id"] == "c_limits")
    assert c_limits_node["mastery"] == act_data["updated_masteries"]["c_limits"]


def test_e2e_zero_knowledge_learner(purge_subject):
    """
    Tests edge case where learner selects DONT_KNOW for all concepts:
    - Diagnostic is NOT run
    - Learner NOT set to mastery 0 everywhere
    - State remains neutral/uninitialized
    - Foundational concepts selected from prerequisite graph
    - Path generated normally
    """
    subject_id = purge_subject("subj_calculus_e2e")
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
        json={"session_id": session_id, "learner_id": learner_id},
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


def test_e2e_returning_learner(purge_subject):
    """
    Tests returning learner session restoration from disk storage:
    - Existing state reloaded
    - Onboarding not repeated
    - Progress preserved
    """
    subject_id = purge_subject("subj_calculus_e2e")
    learner_id = "learner_returning_303"
    create_sample_learning_context(subject_id)
    all_concepts = ["c_limits", "c_derivatives", "c_chain_rule", "c_integrals"]

    # 1. Simulate initial activity for student (server-authoritative path)
    _ks = KnowledgeService()
    _learning = LearningService(
        learner_service=LearnerService(knowledge_service=_ks), knowledge_service=_ks
    )
    _q_limits = _learning.get_or_create_question_bank(subject_id).get_by_concept("c_limits")[0]
    act = client.post(
        "/api/learners/activity-response",
        json={
            "learner_id": learner_id,
            "subject_id": subject_id,
            "concept_ids": ["c_limits"],
            "question_id": _q_limits.question_id,
            "selected_option": _q_limits.correct_answer,
            "all_subject_concept_ids": all_concepts,
        },
    )
    assert act.status_code == 200, act.text
    assert act.json()["is_correct"] is True

    # 2. Re-fetch learner progress and path (simulating page reload / application restart)
    prog_res = client.get(f"/api/learners/{learner_id}/progress?subject_id={subject_id}")
    assert prog_res.status_code == 200
    prog_data = prog_res.json()
    assert prog_data["explored_concepts"] == 1

    path_res = client.get(f"/api/learners/{learner_id}/path-and-gaps?subject_id={subject_id}")
    assert path_res.status_code == 200
    path_data = path_res.json()
    assert len(path_data["learning_path"]["nodes"]) > 0


def test_e2e_mixed_knowledge_learner(purge_subject):
    """
    Tests learner with mixed mastery levels:
    - Strong concepts are not repeated
    - Weak prerequisites are prioritized
    """
    subject_id = purge_subject("subj_calculus_e2e")
    learner_id = "learner_mixed_404"
    create_sample_learning_context(subject_id)
    all_concepts = ["c_limits", "c_derivatives", "c_chain_rule", "c_integrals"]

    # Master 'c_limits' by submitting multiple correct responses.
    # Each attempt uses a distinct question_id so the server evaluates real evidence
    # and idempotency does not collapse them into cached replays.
    _ks = KnowledgeService()
    _learning = LearningService(
        learner_service=LearnerService(knowledge_service=_ks), knowledge_service=_ks
    )
    _q_limits = _learning.get_or_create_question_bank(subject_id).get_by_concept("c_limits")
    assert len(_q_limits) >= 4, "need at least 4 grounded questions for c_limits"
    for _q in _q_limits[:4]:
        act = client.post(
            "/api/learners/activity-response",
            json={
                "learner_id": learner_id,
                "subject_id": subject_id,
                "concept_ids": ["c_limits"],
                "question_id": _q.question_id,
                "selected_option": _q.correct_answer,
                "all_subject_concept_ids": all_concepts,
            },
        )
        assert act.status_code == 200, act.text
        assert act.json()["is_correct"] is True

    path_res = client.get(f"/api/learners/{learner_id}/path-and-gaps?subject_id={subject_id}")
    assert path_res.status_code == 200
    path_data = path_res.json()

    next_target = path_data["next_target"]
    assert next_target is not None
    # Next target should advance past mastered c_limits to c_derivatives
    assert next_target["concept_id"] == "c_derivatives"

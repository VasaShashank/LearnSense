"""
Comprehensive Regression & Integration Tests for Manual Concept Verification
and Curriculum Review Workflow (Person 2).

Validates:
1. Human review decisions (accept, reject, edit name, mark duplicate, propose new canonical, flag).
2. Stable ID preservation and provenance tracking across rename operations.
3. Verbatim evidence verification (pages, block IDs, spans).
4. Canonical mapping corrections and alternative suggested candidates.
5. Hierarchy adjustments (L1, L2, L3) and parent topic reassignment.
6. Prerequisite dependency review with DAG cycle prevention (409 Conflict on cyclic edges).
7. Gating of rejected and duplicate concepts from student diagnostic question generation.
8. REST API endpoints via FastAPI TestClient.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Dict

import pytest
from fastapi.testclient import TestClient

from backend.app import app
from backend.services.concept_review_service import (
    ConceptReviewDecision,
    ConceptReviewStatus,
    ConceptReviewWorkflowService,
)
from backend.services.knowledge_service import KnowledgeService
from backend.services.learning_service import LearningService
from curriculum.models import CurriculumGraph
from curriculum.repository import CurriculumRepository
from curriculum.review import ReviewConflictError
from phase2.models import Evidence, TextSpan
from phase3.knowledge.phase2_adapter import (
    ConceptView,
    LearningContext,
    PrerequisiteLink,
)
from phase4.models import SelfAssessmentStatus
from storage.repositories import LearningContextRepository
from storage.store import DocumentStorage


@pytest.fixture
def review_setup(tmp_path: Path):
    """Sets up an isolated document context with concepts, evidence, and topics."""
    context_repo = LearningContextRepository(base_dir=str(tmp_path / "learning_contexts"))
    curriculum_repo = CurriculumRepository(base_dir=str(tmp_path / "curriculum"))
    doc_storage = DocumentStorage(root_dir=str(tmp_path / "documents"))

    # Seed an official JEE graph
    graph = CurriculumGraph(curriculum_id="jee_main_2027")
    curriculum_repo.save_graph(graph)

    # Build test LearningContext
    doc_id = "doc_physics_laws_review"
    ev1 = Evidence(
        evidence_id="ev_001",
        excerpt="Newton's First Law states that every body continues in its state of rest unless compelled by an external force.",
        block_id="blk_001",
        level="EXPLICIT",
        kind="definition_pattern",
        span=TextSpan(field="text", start=10, end=125),
    )
    ev2 = Evidence(
        evidence_id="ev_002",
        excerpt="The second law states that the rate of change of momentum is proportional to the impressed force.",
        block_id="blk_002",
        level="EXPLICIT",
        kind="definition_pattern",
        span=TextSpan(field="text", start=15, end=115),
    )

    c1 = ConceptView(
        concept_id="c_first_law",
        canonical_name="Newton's First Law",
        type="core",
        description="Law of inertia stating bodies maintain velocity unless acted upon.",
        page_indices=[0],
        evidence_ids=["ev_001"],
        block_ids=["blk_001"],
    )
    c2 = ConceptView(
        concept_id="c_inertia",
        canonical_name="Inertia",
        type="core",
        description="The resistance of any physical object to any change in its velocity.",
        page_indices=[0],
        evidence_ids=["ev_001"],
        block_ids=["blk_001"],
    )
    c3 = ConceptView(
        concept_id="c_second_law",
        canonical_name="Newton's Second Law",
        type="core",
        description="Force equals rate of change of momentum (F = dp/dt).",
        page_indices=[1],
        evidence_ids=["ev_002"],
        block_ids=["blk_002"],
    )

    prereqs = [
        PrerequisiteLink(source_concept_id="c_first_law", target_concept_id="c_second_law", confidence=0.9)
    ]
    topics = [
        {"id": "topic_laws", "name": "Laws of Motion", "level": 1, "concept_ids": ["c_first_law", "c_inertia", "c_second_law"]}
    ]

    ctx = LearningContext(
        document_id=doc_id,
        knowledge_document_id="ekr_laws",
        document_title="NCERT Physics Chapter 5 - Laws of Motion",
        source_filename="laws_of_motion.pdf",
        concepts={"c_first_law": c1, "c_inertia": c2, "c_second_law": c3},
        relationships=[],
        prerequisites=prereqs,
        evidence={"ev_001": ev1, "ev_002": ev2},
        topics=topics,
        metadata={
            "curriculum_id": "jee_main_2027",
            "subject": "Physics",
            "chapter": "Laws of Motion",
            "examination": "JEE_MAIN",
        },
    )
    context_repo.save_context(ctx)

    service = ConceptReviewWorkflowService(
        context_repo=context_repo,
        curriculum_repo=curriculum_repo,
        doc_storage=doc_storage,
    )

    return {
        "service": service,
        "doc_id": doc_id,
        "context_repo": context_repo,
        "curriculum_repo": curriculum_repo,
        "doc_storage": doc_storage,
    }


# -----------------------------------------------------------------------------
# 1. Verification Items & Evidence Loading
# -----------------------------------------------------------------------------


def test_get_document_review_items(review_setup):
    service = review_setup["service"]
    doc_id = review_setup["doc_id"]

    data = service.get_document_review_items(doc_id)
    assert data["document_id"] == doc_id
    assert data["total_concepts"] == 3
    assert data["subject"] == "Physics"
    assert data["target_curriculum"] == "jee_main_2027"

    concepts = data["concepts"]
    assert len(concepts) == 3

    # Check evidence details on first concept
    c1 = next(c for c in concepts if c["concept_id"] == "c_first_law")
    assert c1["canonical_name"] == "Newton's First Law"
    assert c1["page_number"] == 1
    assert "Newton's First Law states" in c1["evidence_excerpt"]
    assert c1["block_id"] == "blk_001"
    assert c1["span"]["start_offset"] == 10
    assert c1["span"]["end_offset"] == 125
    assert c1["review_status"] == ConceptReviewStatus.PENDING_REVIEW.value


# -----------------------------------------------------------------------------
# 2. Review Decisions (Accept, Reject, Edit Name, Duplicate, Flag, New Canonical)
# -----------------------------------------------------------------------------


def test_accept_concept(review_setup):
    service = review_setup["service"]
    doc_id = review_setup["doc_id"]

    res = service.apply_concept_decision(
        document_id=doc_id,
        concept_id="c_first_law",
        decision=ConceptReviewDecision.ACCEPT,
        reviewer_id="teacher_radhika",
        reason="Verified against NCERT Class 11 text.",
    )
    assert res["status"] == "success"
    assert res["review_status"] == ConceptReviewStatus.ACCEPTED.value

    # Verify context persistence
    data = service.get_document_review_items(doc_id)
    c1 = next(c for c in data["concepts"] if c["concept_id"] == "c_first_law")
    assert c1["review_status"] == ConceptReviewStatus.ACCEPTED.value
    assert c1["reviewed_by"] == "teacher_radhika"


def test_edit_concept_name_preserves_stable_id(review_setup):
    service = review_setup["service"]
    doc_id = review_setup["doc_id"]

    res = service.apply_concept_decision(
        document_id=doc_id,
        concept_id="c_inertia",
        decision=ConceptReviewDecision.EDIT_NAME,
        reviewer_id="teacher_radhika",
        new_name="Principle of Inertia",
        reason="Clarified terminology for JEE syllabus.",
    )
    assert res["status"] == "success"
    assert res["canonical_name"] == "Principle of Inertia"

    # Verify ID remains stable and evidence is unchanged
    data = service.get_document_review_items(doc_id)
    c = next(c for c in data["concepts"] if c["concept_id"] == "c_inertia")
    assert c["canonical_name"] == "Principle of Inertia"
    assert c["concept_id"] == "c_inertia"  # ID preserved!
    assert c["block_id"] == "blk_001"     # Provenance preserved!


def test_reject_concept_requires_reason(review_setup):
    service = review_setup["service"]
    doc_id = review_setup["doc_id"]

    with pytest.raises(ValueError, match="reason is required"):
        service.apply_concept_decision(
            document_id=doc_id,
            concept_id="c_second_law",
            decision=ConceptReviewDecision.REJECT,
            reviewer_id="teacher_radhika",
            reason="",
        )

    res = service.apply_concept_decision(
        document_id=doc_id,
        concept_id="c_second_law",
        decision=ConceptReviewDecision.REJECT,
        reviewer_id="teacher_radhika",
        reason="Incidental mention without full derivation.",
    )
    assert res["status"] == "success"
    assert res["review_status"] == ConceptReviewStatus.REJECTED.value


def test_mark_duplicate_concept(review_setup):
    service = review_setup["service"]
    doc_id = review_setup["doc_id"]

    res = service.apply_concept_decision(
        document_id=doc_id,
        concept_id="c_inertia",
        decision=ConceptReviewDecision.MARK_DUPLICATE,
        reviewer_id="teacher_radhika",
        duplicate_of_concept_id="c_first_law",
        reason="Inertia is conceptually sub-sumed under First Law.",
    )
    assert res["status"] == "success"
    assert res["review_status"] == ConceptReviewStatus.DUPLICATE.value


def test_request_new_canonical_concept(review_setup):
    service = review_setup["service"]
    doc_id = review_setup["doc_id"]

    res = service.apply_concept_decision(
        document_id=doc_id,
        concept_id="c_first_law",
        decision=ConceptReviewDecision.REQUEST_NEW_CANONICAL,
        reviewer_id="teacher_radhika",
        reason="Add Newton's First Law as new canonical concept to JEE 2027 graph.",
    )
    assert res["status"] == "success"
    assert res["review_status"] == ConceptReviewStatus.ACCEPTED.value


def test_flag_for_review(review_setup):
    service = review_setup["service"]
    doc_id = review_setup["doc_id"]

    res = service.apply_concept_decision(
        document_id=doc_id,
        concept_id="c_first_law",
        decision=ConceptReviewDecision.FLAG_REVIEW,
        reviewer_id="teacher_radhika",
        status=ConceptReviewStatus.NEEDS_EVIDENCE_REVIEW.value,
        reason="Verify paragraph boundaries on page 1.",
    )
    assert res["status"] == "success"
    assert res["review_status"] == ConceptReviewStatus.NEEDS_EVIDENCE_REVIEW.value


def test_unauthorized_action_missing_reviewer(review_setup):
    service = review_setup["service"]
    doc_id = review_setup["doc_id"]

    with pytest.raises(ValueError, match="reviewer_id is mandatory"):
        service.apply_concept_decision(
            document_id=doc_id,
            concept_id="c_first_law",
            decision=ConceptReviewDecision.ACCEPT,
            reviewer_id="",
        )


# -----------------------------------------------------------------------------
# 3. Hierarchy & Canonical Mapping Adjustments
# -----------------------------------------------------------------------------


def test_hierarchy_level_and_topic_reassignment(review_setup):
    service = review_setup["service"]
    doc_id = review_setup["doc_id"]

    service.apply_concept_decision(
        document_id=doc_id,
        concept_id="c_first_law",
        decision=ConceptReviewDecision.ACCEPT,
        reviewer_id="teacher_radhika",
        new_hierarchical_level="level_1",
        new_parent_topic_id="topic_core_dynamics",
    )

    data = service.get_document_review_items(doc_id)
    c1 = next(c for c in data["concepts"] if c["concept_id"] == "c_first_law")
    assert c1["hierarchical_level"] == "level_1"
    assert c1["parent_topic_id"] == "topic_core_dynamics"


# -----------------------------------------------------------------------------
# 4. Prerequisite Review & Cycle Detection
# -----------------------------------------------------------------------------


def test_prerequisite_approval_and_rejection(review_setup):
    service = review_setup["service"]
    doc_id = review_setup["doc_id"]

    # Approve existing edge c_first_law -> c_second_law
    res = service.apply_prerequisite_decision(
        document_id=doc_id,
        source_concept_id="c_first_law",
        target_concept_id="c_second_law",
        action="approve",
        reviewer_id="teacher_radhika",
    )
    assert res["status"] == "success"
    assert res["prerequisite_status"] == "accepted"

    # Reject edge
    res2 = service.apply_prerequisite_decision(
        document_id=doc_id,
        source_concept_id="c_first_law",
        target_concept_id="c_second_law",
        action="reject",
        reviewer_id="teacher_radhika",
        reason="Second law can be introduced independently.",
    )
    assert res2["status"] == "success"
    assert res2["prerequisite_status"] == "rejected"


def test_prerequisite_cycle_prevention(review_setup):
    service = review_setup["service"]
    doc_id = review_setup["doc_id"]

    # Initial edge: c_first_law -> c_second_law
    # Add edge: c_second_law -> c_inertia
    service.apply_prerequisite_decision(
        document_id=doc_id,
        source_concept_id="c_second_law",
        target_concept_id="c_inertia",
        action="add",
        reviewer_id="teacher_radhika",
    )

    # Attempting to add c_inertia -> c_first_law would form a cycle:
    # c_first_law -> c_second_law -> c_inertia -> c_first_law
    with pytest.raises(ReviewConflictError, match="would create a prerequisite cycle"):
        service.apply_prerequisite_decision(
            document_id=doc_id,
            source_concept_id="c_inertia",
            target_concept_id="c_first_law",
            action="add",
            reviewer_id="teacher_radhika",
        )


# -----------------------------------------------------------------------------
# 5. Batch Approval & Diagnostic Gating Integration
# -----------------------------------------------------------------------------


def test_batch_approval_and_strict_gating(review_setup):
    service = review_setup["service"]
    doc_id = review_setup["doc_id"]
    context_repo = review_setup["context_repo"]

    # 1. Reject c_inertia
    service.apply_concept_decision(
        document_id=doc_id,
        concept_id="c_inertia",
        decision=ConceptReviewDecision.REJECT,
        reviewer_id="teacher_radhika",
        reason="Redundant sub-concept.",
    )

    # 2. Batch approve remaining verified concepts
    res = service.approve_all_verified(
        document_id=doc_id,
        reviewer_id="teacher_radhika",
        reason="Ready for JEE Main student self-assessment.",
    )
    assert res["status"] == "success"
    assert res["approved_count"] == 2  # c_first_law and c_second_law

    # Verify context strict gating flag
    ctx = context_repo.load_context(doc_id)
    assert ctx.metadata["_enforce_strict_approval"] is True

    # 3. Test Diagnostic Gating in LearningService
    knowledge_service = KnowledgeService(context_repo=context_repo)
    learning_service = LearningService(knowledge_service=knowledge_service)

    # When student submits self-assessment: rejected concept c_inertia MUST be excluded!
    session = learning_service.submit_self_assessment(
        learner_id="student_deepa",
        subject_id=doc_id,
        selections={
            "c_first_law": SelfAssessmentStatus.KNOW,
            "c_second_law": SelfAssessmentStatus.UNANSWERED,
            "c_inertia": SelfAssessmentStatus.KNOW,  # Client submitted rejected concept
        },
    )
    # Server authority must prune c_inertia
    assert "c_inertia" not in session.know_concept_ids
    assert "c_first_law" in session.know_concept_ids
    assert "c_second_law" in session.unanswered_concept_ids

    # 4. Test KnowledgeService.get_subject_graph excludes rejected concept
    graph_view = knowledge_service.get_subject_graph(doc_id)
    concept_ids_in_graph = [c["concept_id"] for c in graph_view["concepts"]]
    assert "c_inertia" not in concept_ids_in_graph
    assert "c_first_law" in concept_ids_in_graph
    assert "c_second_law" in concept_ids_in_graph


# -----------------------------------------------------------------------------
# 6. Audit Trail Immutability
# -----------------------------------------------------------------------------


def test_audit_history_recording(review_setup):
    service = review_setup["service"]
    doc_id = review_setup["doc_id"]

    service.apply_concept_decision(
        document_id=doc_id,
        concept_id="c_first_law",
        decision=ConceptReviewDecision.ACCEPT,
        reviewer_id="teacher_radhika",
        reason="Initial approval",
    )
    service.apply_concept_decision(
        document_id=doc_id,
        concept_id="c_first_law",
        decision=ConceptReviewDecision.EDIT_NAME,
        reviewer_id="teacher_radhika",
        new_name="Newton's First Law of Motion",
        reason="Updated title",
    )

    history = service.get_audit_history(doc_id)
    assert len(history) == 2
    assert history[0]["action"] == "accept"
    assert history[0]["reviewer_id"] == "teacher_radhika"
    assert history[1]["action"] == "edit_name"
    assert history[1]["previous_name"] == "Newton's First Law"
    assert history[1]["new_name"] == "Newton's First Law of Motion"


# -----------------------------------------------------------------------------
# 7. FastAPI REST API Integration
# -----------------------------------------------------------------------------


def test_rest_api_concept_review_endpoints(review_setup, monkeypatch):
    service = review_setup["service"]
    doc_id = review_setup["doc_id"]

    # Route dependency override
    from backend.routes.curriculum import get_concept_review_service

    app.dependency_overrides[get_concept_review_service] = lambda: service

    try:
        client = TestClient(app)

        # GET /documents/{document_id}/review-items
        r_get = client.get(f"/api/curriculum/documents/{doc_id}/review-items")
        assert r_get.status_code == 200
        data = r_get.json()
        assert data["total_concepts"] == 3

        # POST /documents/{document_id}/review/decision (Accept)
        r_post = client.post(
            f"/api/curriculum/documents/{doc_id}/review/decision",
            json={
                "concept_id": "c_first_law",
                "decision": "accept",
                "reviewer_id": "teacher_api",
                "reason": "REST API verification",
            },
        )
        assert r_post.status_code == 200
        assert r_post.json()["review_status"] == "accepted"

        # POST /documents/{document_id}/review/prerequisite (Cycle -> 409 Conflict)
        service.apply_prerequisite_decision(doc_id, "c_first_law", "c_second_law", "add", "teacher_api")
        service.apply_prerequisite_decision(doc_id, "c_second_law", "c_inertia", "add", "teacher_api")

        r_cycle = client.post(
            f"/api/curriculum/documents/{doc_id}/review/prerequisite",
            json={
                "source_concept_id": "c_inertia",
                "target_concept_id": "c_first_law",
                "action": "add",
                "reviewer_id": "teacher_api",
            },
        )
        assert r_cycle.status_code == 409
        assert "prerequisite cycle" in r_cycle.json()["detail"].lower()

        # POST /documents/{document_id}/review/approve-batch
        r_batch = client.post(
            f"/api/curriculum/documents/{doc_id}/review/approve-batch",
            json={"reviewer_id": "teacher_api", "reason": "Batch API approval"},
        )
        assert r_batch.status_code == 200
        assert r_batch.json()["status"] == "success"

        # GET /documents/{document_id}/review/audit-history
        r_audit = client.get(f"/api/curriculum/documents/{doc_id}/review/audit-history")
        assert r_audit.status_code == 200
        assert r_audit.json()["count"] > 0

        # GET /documents/{document_id}/pages/1/evidence
        r_page = client.get(f"/api/curriculum/documents/{doc_id}/pages/1/evidence")
        assert r_page.status_code == 200
        assert "raw_text" in r_page.json()

    finally:
        app.dependency_overrides.clear()

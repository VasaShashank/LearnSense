"""
Phase 5 End-to-End Pipeline Integration & Recovery Test Suite.
"""

import time
import pytest
from fastapi.testclient import TestClient
from backend.app import app
from phase3.knowledge.phase2_adapter import ConceptView, LearningContext, PrerequisiteLink
from phase3.learner.models import LearnerState
from phase4.integration.phase3_adapter import Phase3Adapter
from phase5.validation import KnowledgeGraphValidator, InputValidator, ExtractionValidator

client = TestClient(app)


def test_api_upload_invalid_file_rejected():
    """Verify Phase 5 input validation rejects non-PDF upload."""
    response = client.post("/documents", files={"file": ("invalid.txt", b"hello world", "text/plain")})
    assert response.status_code == 400
    assert "PDF" in response.json()["detail"]


def test_api_activity_response_idempotency(ingested_calculus):
    """
    Verify duplicate activity response submission is handled idempotently without
    double KT update.

    Exercises the REAL server-authoritative path: a question_id plus the selected
    option. The legacy `correctness`-only shortcut is no longer reachable over HTTP.
    """
    from backend.services.knowledge_service import KnowledgeService
    from backend.services.learner_service import LearnerService
    from backend.services.learning_service import LearningService

    subject_id = ingested_calculus.document_id
    concept_id = ingested_calculus.concept_ids[0]

    ks = KnowledgeService()
    learning = LearningService(
        learner_service=LearnerService(knowledge_service=ks), knowledge_service=ks
    )
    question = learning.get_or_create_question_bank(subject_id).get_grounded_questions()[0]

    payload = {
        "learner_id": f"learner_p5_test_{int(time.time())}",
        "subject_id": subject_id,
        "concept_ids": [concept_id],
        "question_id": question.question_id,
        "selected_option": question.correct_answer,
        "all_subject_concept_ids": list(ingested_calculus.concept_ids),
        "request_id": f"req_unique_token_{int(time.time() * 1000)}",
    }

    # First attempt
    res1 = client.post("/api/learners/activity-response", json=payload)
    assert res1.status_code == 200, res1.text
    data1 = res1.json()
    assert "duplicate_submission" not in data1 or data1.get("duplicate_submission") is False
    first_masteries = data1["updated_masteries"]

    # Second duplicate attempt with same request_id
    res2 = client.post("/api/learners/activity-response", json=payload)
    assert res2.status_code == 200, res2.text
    data2 = res2.json()
    assert data2.get("duplicate_submission") is True
    # The cached replay must not apply a second BKT update.
    assert data2["updated_masteries"] == first_masteries


def test_api_activity_response_rejects_client_correctness(ingested_calculus):
    """
    P0 SECURITY: the API must never accept client-reported correctness.
    This is the exact bypass that previously let a client forge mastery.
    """
    subject_id = ingested_calculus.document_id
    concept_id = ingested_calculus.concept_ids[0]

    res = client.post(
        "/api/learners/activity-response",
        json={
            "learner_id": f"learner_p5_forge_{int(time.time())}",
            "subject_id": subject_id,
            "concept_ids": [concept_id],
            "correctness": 1.0,
            "all_subject_concept_ids": list(ingested_calculus.concept_ids),
        },
    )
    assert res.status_code == 400, (
        f"SECURITY VIOLATION: client correctness accepted: {res.text}"
    )
    assert "question_id" in res.json()["detail"]


def test_end_to_end_graph_cycle_recovery_pipeline():
    """Verify end-to-end knowledge graph cycle detection and recovery protects Phase 4 planner."""
    context = LearningContext(document_id="doc_cycle_test", knowledge_document_id="kdoc_cycle_test")
    context.concepts["A"] = ConceptView(concept_id="A", canonical_name="Concept A", type="concept")
    context.concepts["B"] = ConceptView(concept_id="B", canonical_name="Concept B", type="concept")
    context.concepts["C"] = ConceptView(concept_id="C", canonical_name="Concept C", type="concept")

    # Introduce cycle A -> B -> C -> A
    context.prerequisites = [
        PrerequisiteLink(source_concept_id="A", target_concept_id="B", confidence=1.0),
        PrerequisiteLink(source_concept_id="B", target_concept_id="C", confidence=1.0),
        PrerequisiteLink(source_concept_id="C", target_concept_id="A", confidence=1.0),
    ]

    validator = KnowledgeGraphValidator()
    val_res = validator.validate_learning_context(context)
    assert val_res.metadata["cycles_count"] == 1

    # Sanitize graph cycle
    sanitized_context = validator.sanitize_and_break_cycles(context)

    # Verify Phase 4 path generation runs safely on sanitized graph without infinite recursion
    adapter = Phase3Adapter()
    learner_state = adapter.tracer.initialize_learner("learner_cycle_test", ["A", "B", "C"])
    path = adapter.path_generator.generate_path(sanitized_context, learner_state, ["A", "B", "C"])

    assert path is not None
    assert len(path.nodes) > 0
    node_ids = [n.concept_id for n in path.nodes]
    assert len(node_ids) == len(set(node_ids))  # No duplicate cycle loops in path

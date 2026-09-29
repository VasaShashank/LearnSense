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


def test_api_activity_response_idempotency():
    """Verify duplicate activity response submission is handled idempotently without double KT update."""
    from phase3.knowledge.phase2_adapter import ConceptView, LearningContext
    from storage.repositories import LearningContextRepository
    repo = LearningContextRepository()
    ctx = LearningContext(document_id="subj_p5_test", knowledge_document_id="kdoc_p5_test")
    ctx.concepts["c1"] = ConceptView(concept_id="c1", canonical_name="Concept 1", type="concept")
    ctx.concepts["c2"] = ConceptView(concept_id="c2", canonical_name="Concept 2", type="concept")
    repo.save_context(ctx)

    payload = {
        "learner_id": "learner_p5_test",
        "subject_id": "subj_p5_test",
        "concept_ids": ["c1"],
        "correctness": 1.0,
        "all_subject_concept_ids": ["c1", "c2"],
        "request_id": f"req_unique_token_{int(time.time() * 1000)}",
    }

    # First attempt
    res1 = client.post("/api/learners/activity-response", json=payload)
    assert res1.status_code == 200
    data1 = res1.json()
    assert "duplicate_submission" not in data1 or data1.get("duplicate_submission") is False

    # Second duplicate attempt with same request_id
    res2 = client.post("/api/learners/activity-response", json=payload)
    assert res2.status_code == 200
    data2 = res2.json()
    assert data2.get("duplicate_submission") is True


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

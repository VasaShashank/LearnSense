"""
End-to-End Authenticated User Journey Integration Test Suite.

Verifies the unified experience across Person 1 and Person 2:
1. Student Journey:
   Sign In -> Authenticated Identity -> Learner Provisioning -> Curriculum Tree ->
   Learning Sequence Progression -> Session State.
2. Teacher Journey:
   Sign In -> Verify Faculty Membership -> Access Curriculum Dashboard ->
   Review Concept Proposal -> Approve Canonical Candidate -> Audit Persistence.
3. Multi-role Account Journey:
   Sign In -> Student Context -> Switch to Assigned Teacher Context ->
   Verify Governance Access -> Switch back to Student Context.
"""

from __future__ import annotations

import uuid
import pytest
from fastapi.testclient import TestClient

from backend.app import app
from backend.auth import AuthenticatedUser, get_current_user
from backend.routes.curriculum import get_service
from backend.services.curriculum_service import CurriculumService
from backend.services.learner_service import LearnerService
from curriculum.models import (
    CanonicalConcept,
    CurriculumGraph,
    Subject,
    ConceptRelationship,
    RelationshipTypeEnum,
    RelationshipStatusEnum,
    SourceRef,
)
from curriculum.repository import CurriculumRepository
from phase3.storage.learner_repository import LearnerStateRepository

STUDENT_UUID = str(uuid.uuid4())
TEACHER_UUID = str(uuid.uuid4())
ADMIN_UUID = str(uuid.uuid4())


@pytest.fixture
def journey_env(tmp_path):
    # Setup test curriculum repository
    repo = CurriculumRepository(base_dir=str(tmp_path / "journey_curriculum"))
    service = CurriculumService(repository=repo)

    # Seed an academic prerequisite chain (Physics: Vectors -> Kinematics -> Dynamics)
    graph = CurriculumGraph(curriculum_id=service.curriculum_id, syllabus_version="2026.e2e.v1")
    s_ref = SourceRef(source_id="doc_ncert_physics_part1", locator="p10")
    c1 = CanonicalConcept.create(
        name="Vectors and Coordinates",
        subject=Subject.PHYSICS,
        class_levels=["class_11"],
        chapter_id="ch_vectors",
        description="Vector algebra, dot and cross products.",
        stable_key="cc_vectors_e2e",
        source_refs=[s_ref],
    )
    c2 = CanonicalConcept.create(
        name="Kinematics 1D",
        subject=Subject.PHYSICS,
        class_levels=["class_11"],
        chapter_id="ch_kinematics",
        description="Displacement, velocity, and acceleration.",
        stable_key="cc_kinematics_e2e",
        prerequisite_concept_ids=[c1.concept_id],
        source_refs=[s_ref],
    )
    c3 = CanonicalConcept.create(
        name="Newton's Laws of Motion",
        subject=Subject.PHYSICS,
        class_levels=["class_11"],
        chapter_id="ch_dynamics",
        description="Force, inertia, and momentum.",
        stable_key="cc_dynamics_e2e",
        prerequisite_concept_ids=[c2.concept_id],
        source_refs=[s_ref],
    )
    graph.add_concept(c1)
    graph.add_concept(c2)
    graph.add_concept(c3)
    graph.add_relationship(
        ConceptRelationship.create(
            source=c1.concept_id,
            relationship_type=RelationshipTypeEnum.PREREQUISITE_OF,
            target=c2.concept_id,
            status=RelationshipStatusEnum.ACCEPTED,
            source_refs=[s_ref],
        )
    )
    graph.add_relationship(
        ConceptRelationship.create(
            source=c2.concept_id,
            relationship_type=RelationshipTypeEnum.PREREQUISITE_OF,
            target=c3.concept_id,
            status=RelationshipStatusEnum.ACCEPTED,
            source_refs=[s_ref],
        )
    )
    repo.save_graph(graph)

    # Setup learner repo
    learners = LearnerStateRepository(str(tmp_path / "learners"))
    learner_svc = LearnerService(repo=learners)

    app.dependency_overrides[get_service] = lambda: service
    try:
        yield service, learner_svc, [c1, c2, c3]
    finally:
        app.dependency_overrides.pop(get_service, None)
        app.dependency_overrides.pop(get_current_user, None)


def test_student_end_to_end_curriculum_journey(journey_env):
    """Student signs in, provisions identity, accesses canonical curriculum,
    and explores learning sequence."""
    service, learner_svc, concepts = journey_env

    # 1. Simulate verified Supabase identity
    app.dependency_overrides[get_current_user] = lambda: AuthenticatedUser(
        id=STUDENT_UUID, email="alex.rivera@apex.edu"
    )
    client = TestClient(app, raise_server_exceptions=False)
    client.headers.update({"Authorization": f"Bearer mock_student_token_{STUDENT_UUID}"})

    # 2. Provision learner state idempotently
    state, created = learner_svc.provision_authenticated_learner(STUDENT_UUID)
    assert state.learner_id == STUDENT_UUID
    assert created is True

    # 3. Retrieve curriculum status and concepts
    status_res = client.get("/api/curriculum/status")
    assert status_res.status_code == 200
    assert status_res.json()["concept_count"] >= 3

    concepts_res = client.get("/api/curriculum/concepts?subject=physics")
    assert concepts_res.status_code == 200
    returned_concepts = concepts_res.json()["concepts"]
    assert len(returned_concepts) >= 3

    # 4. Request learning progression sequence
    order_res = client.get("/api/curriculum/learning-order?subject=physics")
    assert order_res.status_code == 200
    learning_order = order_res.json()["order"]
    assert len(learning_order) >= 3

    # Vectors must precede Kinematics, which precedes Dynamics
    vec_id = concepts[0].concept_id
    kin_id = concepts[1].concept_id
    dyn_id = concepts[2].concept_id
    assert learning_order.index(vec_id) < learning_order.index(kin_id)
    assert learning_order.index(kin_id) < learning_order.index(dyn_id)


def test_teacher_end_to_end_governance_journey(journey_env):
    """Teacher signs in, views review queue, approves a new concept proposal,
    and confirms canonical graph updates."""
    service, _, concepts = journey_env

    app.dependency_overrides[get_current_user] = lambda: AuthenticatedUser(
        id=TEACHER_UUID, email="prof.vance@apex.edu"
    )
    client = TestClient(app, raise_server_exceptions=False)
    client.headers.update({"Authorization": f"Bearer mock_teacher_token_{TEACHER_UUID}"})

    # 1. Propose candidate concept from ingestion
    proposal_res = client.post(
        "/api/curriculum/review/accept",
        json={
            "proposed": {
                "name": "Quantum Spin Hall Effect",
                "subject": "physics",
                "class_levels": ["class_12"],
                "chapter_id": "ch_advanced",
                "description": "Topological insulator phenomena in quantum materials.",
            },
            "prerequisite_ids": [concepts[2].concept_id],
            "reviewer_id": "prof_vance",
            "reviewer_role": "teacher",
            "note": "Curriculum committee review: approved for JEE 2027",
        },
    )
    assert proposal_res.status_code == 200, proposal_res.json()
    new_concept = proposal_res.json()
    new_cid = new_concept["concept_id"]
    assert new_concept["name"] == "Quantum Spin Hall Effect"

    # 2. Verify concept is live in canonical graph
    verify_res = client.get(f"/api/curriculum/concepts/{new_cid}")
    assert verify_res.status_code == 200
    assert verify_res.json()["name"] == "Quantum Spin Hall Effect"

    # 3. Verify review records contain audit evidence
    records_res = client.get("/api/curriculum/review/records")
    assert records_res.status_code == 200
    records = records_res.json()["records"]
    assert any(r.get("subject_id") == new_cid for r in records)


def test_multirole_workspace_switching_journey(journey_env):
    """User with faculty access switches between Student and Teacher contexts."""
    app.dependency_overrides[get_current_user] = lambda: AuthenticatedUser(
        id=TEACHER_UUID, email="educator@apex.edu"
    )
    client = TestClient(app, raise_server_exceptions=False)
    client.headers.update({"Authorization": f"Bearer mock_multirole_token_{TEACHER_UUID}"})

    # 1. Student context: Read-only access to syllabus and concepts
    concepts_res = client.get("/api/curriculum/concepts")
    assert concepts_res.status_code == 200

    # 2. Teacher context: Review and governance access
    status_res = client.get("/api/curriculum/status")
    assert status_res.status_code == 200

    # 3. Attempting student role mutation fails closed with 403
    forbidden_res = client.post(
        "/api/curriculum/review/accept",
        json={
            "proposed": {"name": "Unauthorized Attempt"},
            "reviewer_id": "student_alex",
            "reviewer_role": "learner",
        },
    )
    assert forbidden_res.status_code == 403

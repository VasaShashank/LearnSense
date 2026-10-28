"""
Integration tests for Institutional Architecture, B2B Multi-Tenancy,
and New REST Endpoints for Resources & Teacher Optimizer (§9, §10, §11).
"""

import uuid
import pytest
from fastapi.testclient import TestClient
from backend.app import app
from phase4.institution.models import UserRole
from phase3.errors import AuthorizationError

client = TestClient(app)


def test_resource_api_endpoints(ingested_calculus):
    subject_id = ingested_calculus.document_id
    concept_id = ingested_calculus.concept_ids[0]

    # 1. Fetch recommendations for concept
    res = client.get(f"/api/subjects/{subject_id}/concepts/{concept_id}/resources")
    assert res.status_code == 200, res.text
    data = res.json()
    assert isinstance(data, list)
    assert len(data) > 0
    top = data[0]
    assert "resource_id" in top
    assert "overall_score" in top
    assert "notation_score" in top
    assert "recommended_timestamp_seconds" in top

    # 2. Fetch specific resource by ID
    rid = top["resource_id"]
    res_detail = client.get(f"/api/resources/{rid}")
    assert res_detail.status_code == 200
    assert res_detail.json()["resource_id"] == rid


def test_teacher_optimizer_and_class_api(ingested_calculus):
    subject_id = ingested_calculus.document_id
    concept_id = ingested_calculus.concept_ids[0]
    class_id = "cls_integration_test_101"

    # 1. Register Class
    reg_res = client.post(
        f"/api/classes?class_id={class_id}",
        json={
            "subject_id": subject_id,
            "class_name": "Integration Test Section A",
            "enrolled_learner_ids": ["learner_a", "learner_b", "learner_c"],
        },
    )
    assert reg_res.status_code == 200, reg_res.text
    assert reg_res.json()["class_id"] == class_id

    # 2. Get Class Knowledge State
    state_res = client.get(f"/api/classes/{class_id}/knowledge-state")
    assert state_res.status_code == 200, state_res.text
    state_data = state_res.json()
    assert state_data["class_id"] == class_id
    assert state_data["total_enrolled"] == 3
    assert concept_id in state_data["concept_distributions"]

    # 3. Generate Teaching Optimizer Plan
    plan_res = client.post(
        f"/api/classes/{class_id}/teaching-optimizer/plan",
        json={
            "subject_id": subject_id,
            "target_concept_id": concept_id,
            "duration_minutes": 45,
        },
    )
    assert plan_res.status_code == 200, plan_res.text
    plan_data = plan_res.json()
    assert plan_data["status"] == "PROPOSED"
    assert len(plan_data["actions"]) >= 2
    intervention_id = plan_data["intervention_id"]

    # 4. Approve Plan
    approve_res = client.post(
        f"/api/classes/{class_id}/interventions/{intervention_id}/approve",
        json={"teacher_notes": "Approved for 2nd period class session."},
    )
    assert approve_res.status_code == 200, approve_res.text
    assert approve_res.json()["status"] == "APPROVED"
    assert approve_res.json()["teacher_notes"] == "Approved for 2nd period class session."


def test_institutional_rbac_and_tenant_isolation(tmp_path, monkeypatch):
    # This service-level regression deliberately exercises the JSON backend;
    # never inherit a developer's local DATABASE_URL or require-PG setting.
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("LEARNSENSE_REQUIRE_PG", raising=False)
    monkeypatch.chdir(tmp_path)
    from backend.services.institution_service import InstitutionService
    from phase3.learner.models import LearnerState
    from phase3.storage.learner_repository import LearnerStateRepository

    learner_id = str(uuid.UUID("a20d9df0-2792-4fc2-9d94-20ac476863e0"))
    learner_repo = LearnerStateRepository(str(tmp_path / "learner_states"))
    learner_repo.save_state(
        LearnerState(learner_id=learner_id, identity_provider="supabase")
    )
    svc = InstitutionService(
        base_dir=str(tmp_path / "institutions"), learner_state_repo=learner_repo
    )

    # 1. Create Organization
    org1 = svc.create_organization(name="Apex University")
    org2 = svc.create_organization(name="Beacon College")

    # 2. Assign Memberships
    svc.add_membership(org1.org_id, "user_prof_smith", UserRole.TEACHER)
    svc.add_membership(org1.org_id, learner_id, UserRole.LEARNER)
    svc.add_membership(org2.org_id, "user_intruder", UserRole.TEACHER)

    # 3. Create Class in Org 1 by Teacher in Org 1 (Allowed)
    cls = svc.create_class(
        org_id=org1.org_id,
        subject_id="subj_calc",
        title="Calculus I - Section 01",
        teacher_ids=["user_prof_smith"],
        creator_user_id="user_prof_smith",
    )
    assert cls.class_id.startswith("cls_")

    # 4. Learner tries to create class -> AuthorizationError
    with pytest.raises(AuthorizationError):
        svc.create_class(
            org_id=org1.org_id,
            subject_id="subj_calc",
            title="Unauthorized Class",
            teacher_ids=[learner_id],
            creator_user_id=learner_id,
        )

    # 5. Teacher from Org 2 tries to access Org 1 class roster -> Cross-tenant isolated
    with pytest.raises(AuthorizationError):
        svc.get_class_roster(class_id=cls.class_id, caller_user_id="user_intruder")

    # 6. Teacher from Org 1 enrolls student and views roster -> Allowed
    svc.enroll_learner(class_id=cls.class_id, learner_id=learner_id, enroller_user_id="user_prof_smith")
    roster = svc.get_class_roster(class_id=cls.class_id, caller_user_id="user_prof_smith")
    assert learner_id in roster

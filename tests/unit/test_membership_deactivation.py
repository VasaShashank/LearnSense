"""Membership deactivation and access revocation.

JSON mode runs against the real InstitutionService in tmp_path; the PostgreSQL path
is exercised with a fake repository and pool. No database is contacted (the
conftest guard stays active).
"""

from types import SimpleNamespace
import asyncio
import uuid

import pytest
from fastapi.testclient import TestClient

from backend.app import app
from backend.auth import AuthenticatedUser, get_current_user
from backend.repositories.institution_repository import InstitutionRepository
from backend.routes import api as api_route
from backend.routes import documents as documents_route
from backend.services import institution_service as inst_mod
from backend.services.institution_service import (
    InstitutionService,
    LastAdminError,
    MembershipNotFoundError,
)
from backend.services.learner_service import LearnerService
from phase3.errors import AuthorizationError
from phase3.storage.learner_repository import LearnerStateRepository
from phase4.institution.models import OrgMembership, UserRole
from storage.document_ownership import DocumentOwnershipRepository
from storage.document_shares import DocumentShareRepository
from storage.job_repository import JobRepository

ADMIN1, ADMIN2, TEACHER, LEARNER, LEARNER2, ADMIN_B = (str(uuid.uuid4()) for _ in range(6))
DOC = "doc_deactivation_material"


@pytest.fixture
def env(monkeypatch, tmp_path):
    learners = LearnerStateRepository(str(tmp_path / "learners"))
    svc = InstitutionService(base_dir=str(tmp_path / "inst"), learner_state_repo=learners)
    assert svc._pg_enabled is False

    projections: dict = {}

    def sync(class_id, subject_id, title, roster):
        projections[class_id] = {
            "class_id": class_id, "subject_id": subject_id, "class_name": title,
            "enrolled_learner_ids": list(roster),
        }

    monkeypatch.setattr(svc, "_sync_class_to_teacher_storage", sync)
    monkeypatch.setattr(
        svc, "_append_learner_to_teacher_storage",
        lambda cid, lid: projections[cid]["enrolled_learner_ids"].append(lid),
    )
    monkeypatch.setattr(
        svc, "_set_teacher_storage_roster",
        lambda cid, roster: projections[cid].__setitem__("enrolled_learner_ids", list(roster)),
    )

    ownership = DocumentOwnershipRepository(str(tmp_path / "owners"))
    shares = DocumentShareRepository(str(tmp_path / "shares"))
    ownership.claim(DOC, TEACHER)
    for lid in (LEARNER, LEARNER2):
        LearnerService(repo=learners).provision_authenticated_learner(lid)
    # Staff role grants require users who have signed in (provisioned user records).
    for uid in (ADMIN1, ADMIN2, TEACHER, ADMIN_B):
        asyncio.run(svc.users.ensure_user(uid, None))

    org_a, org_b = svc.create_organization("Org A"), svc.create_organization("Org B")
    for user, role in ((ADMIN1, UserRole.ADMIN), (ADMIN2, UserRole.ADMIN),
                       (TEACHER, UserRole.TEACHER), (LEARNER, UserRole.LEARNER),
                       (LEARNER2, UserRole.LEARNER)):
        svc.add_membership(org_a.org_id, user, role)
    svc.add_membership(org_b.org_id, ADMIN_B, UserRole.ADMIN)
    cls = svc.create_class(org_a.org_id, DOC, "Class A", [TEACHER], TEACHER, [LEARNER, LEARNER2])

    teacher_svc = SimpleNamespace(
        get_class=lambda cid: projections.get(cid),
        list_classes=lambda: list(projections.values()),
        get_class_knowledge_state=lambda cid, **_k: {
            "enrolled": list(projections[cid]["enrolled_learner_ids"])
        },
    )

    monkeypatch.setattr(api_route, "institution_service", svc)
    monkeypatch.setattr(api_route, "document_ownership", ownership)
    monkeypatch.setattr(api_route, "document_shares", shares)
    monkeypatch.setattr(api_route, "job_repo", JobRepository(str(tmp_path / "jobs")))
    monkeypatch.setattr(api_route, "teacher_service", teacher_svc)
    for access in (api_route.document_access, documents_route.document_access):
        monkeypatch.setattr(access, "ownership", ownership)
        monkeypatch.setattr(access, "shares", shares)
        monkeypatch.setattr(access, "institutions", svc)
    return SimpleNamespace(
        svc=svc, org=org_a, org_b=org_b, cls=cls, projections=projections,
        learners=learners, tmp=tmp_path,
    )


def _call(user_id, method, path, **kwargs):
    app.dependency_overrides[get_current_user] = lambda: AuthenticatedUser(id=user_id, email=None)
    try:
        return TestClient(app, raise_server_exceptions=False).request(method, path, **kwargs)
    finally:
        app.dependency_overrides.pop(get_current_user, None)


def _deactivate(env, caller, target, org_id=None):
    return _call(caller, "DELETE",
                 f"/api/institutions/organizations/{org_id or env.org.org_id}/memberships/{target}")


def _active(env, user):
    m = env.svc.get_membership(env.org.org_id, user)
    return bool(m and m.is_active)


# --- Authorization -----------------------------------------------------------

def test_active_admin_deactivates_member_and_membership_is_retained(env):
    response = _deactivate(env, ADMIN1, TEACHER)
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "deactivated"
    membership = env.svc.get_membership(env.org.org_id, TEACHER)
    assert membership is not None and membership.is_active is False  # retained, not deleted


@pytest.mark.parametrize("caller", [TEACHER, LEARNER])
def test_non_admin_cannot_deactivate(env, caller):
    response = _deactivate(env, caller, LEARNER2)
    assert response.status_code == 403, response.text
    assert _active(env, LEARNER2)


def test_cross_organization_admin_cannot_deactivate(env):
    assert _deactivate(env, ADMIN_B, TEACHER).status_code == 403
    assert _active(env, TEACHER)
    assert _deactivate(env, ADMIN_B, TEACHER, org_id="org_does_not_exist").status_code == 403


def test_unauthenticated_request_is_rejected(env):
    response = TestClient(app).delete(
        f"/api/institutions/organizations/{env.org.org_id}/memberships/{TEACHER}"
    )
    assert response.status_code == 401


# --- Last admin --------------------------------------------------------------

def test_last_active_admin_cannot_be_deactivated(env):
    assert _deactivate(env, ADMIN1, ADMIN2).status_code == 200
    response = _deactivate(env, ADMIN1, ADMIN1)  # ADMIN1 is now the only active admin
    assert response.status_code == 409, response.text
    assert _active(env, ADMIN1)


def test_a_deactivated_admin_loses_admin_rights_immediately(env):
    assert _deactivate(env, ADMIN1, ADMIN2).status_code == 200
    assert _deactivate(env, ADMIN2, ADMIN1).status_code == 403
    assert _active(env, ADMIN1)


def test_admin_may_deactivate_self_when_another_admin_remains(env):
    assert _deactivate(env, ADMIN1, ADMIN1).status_code == 200
    assert _deactivate(env, ADMIN1, TEACHER).status_code == 403


# --- Already inactive / nonexistent ------------------------------------------

def test_already_inactive_is_idempotent_and_unknown_member_is_404(env):
    assert _deactivate(env, ADMIN1, LEARNER).json()["status"] == "deactivated"
    again = _deactivate(env, ADMIN1, LEARNER)
    assert again.status_code == 200 and again.json()["status"] == "already_inactive"
    missing = _deactivate(env, ADMIN1, str(uuid.uuid4()))
    assert missing.status_code == 404


def test_non_admin_cannot_probe_membership_existence(env):
    assert _deactivate(env, TEACHER, str(uuid.uuid4())).status_code == 403


# --- Immediate access revocation ----------------------------------------------

def test_deactivated_teacher_loses_class_and_org_access_immediately(env):
    cid = env.cls.class_id
    org = env.org.org_id
    controls = [
        ("GET", f"/api/institutions/classes/{cid}/roster"),
        ("GET", f"/api/classes/{cid}/knowledge-state"),
    ]
    for method, path in controls:
        assert _call(TEACHER, method, path).status_code == 200, path
    assert _call(TEACHER, "POST", f"/api/classes/{cid}/materials/{DOC}/share").status_code == 200
    orgs = _call(TEACHER, "GET", "/api/institutions/organizations").json()
    assert org in {o["org_id"] for o in orgs}
    assert _deactivate(env, ADMIN1, TEACHER).status_code == 200

    for method, path in controls:
        assert _call(TEACHER, method, path).status_code in (403, 404), path
    assert _call(TEACHER, "POST", f"/api/classes/{cid}/materials/{DOC}/share").status_code in (403, 404)
    assert _call(TEACHER, "GET", "/api/institutions/classes").json() == []
    assert _call(TEACHER, "GET", "/api/classes").json() == []
    assert _call(TEACHER, "GET", "/api/institutions/organizations").json() == []


def test_deactivated_learner_loses_shared_document_access_immediately(env):
    cid = env.cls.class_id
    assert _call(TEACHER, "POST", f"/api/classes/{cid}/materials/{DOC}/share").status_code == 200
    assert api_route.document_access.can_read(DOC, LEARNER)
    api_route._require_owned_uploaded_document(DOC, LEARNER)  # route guard: allowed

    assert _deactivate(env, ADMIN1, LEARNER).status_code == 200

    assert not api_route.document_access.can_read(DOC, LEARNER)
    with pytest.raises(api_route.HTTPException) as denied:       # same guard: now denied
        api_route._require_owned_uploaded_document(DOC, LEARNER)
    assert denied.value.status_code == 404
    assert api_route.document_access.can_read(DOC, LEARNER2)  # others unaffected


def test_deactivated_admin_cannot_manage_memberships_or_classes(env):
    assert _deactivate(env, ADMIN1, ADMIN2).status_code == 200
    add = _call(ADMIN2, "POST", "/api/institutions/memberships",
                json={"org_id": env.org.org_id, "user_id": LEARNER, "role": "LEARNER"})
    assert add.status_code == 403
    assert _call(ADMIN2, "GET", f"/api/institutions/classes/{env.cls.class_id}/roster").status_code in (403, 404)


# --- Active roster / analytics, historical retention --------------------------

def test_deactivated_learner_leaves_active_roster_and_current_analytics(env):
    cid = env.cls.class_id
    before = _call(TEACHER, "GET", f"/api/institutions/classes/{cid}/roster").json()["roster"]
    assert set(before) == {LEARNER, LEARNER2}

    assert _deactivate(env, ADMIN1, LEARNER).status_code == 200

    roster = _call(TEACHER, "GET", f"/api/institutions/classes/{cid}/roster").json()["roster"]
    assert roster == [LEARNER2]
    assert env.projections[cid]["enrolled_learner_ids"] == [LEARNER2]
    # Analytics stay reachable (no projection/roster mismatch lockout) and exclude them.
    analytics = _call(TEACHER, "GET", f"/api/classes/{cid}/knowledge-state")
    assert analytics.status_code == 200, analytics.text
    assert analytics.json()["enrolled"] == [LEARNER2]
    listed = _call(TEACHER, "GET", "/api/classes").json()
    assert listed[0]["enrolled_learner_ids"] == [LEARNER2]


def test_history_is_retained_and_reactivation_restores_the_roster(env):
    cid = env.cls.class_id
    assert _deactivate(env, ADMIN1, LEARNER).status_code == 200

    enrollment = env.svc.enrollments_dir / f"enr_{cid}_{LEARNER}.json"
    assert enrollment.exists()                                   # enrollment retained
    assert env.learners.load_state(LEARNER) is not None          # learner record retained
    assert (env.svc.members_dir / f"{env.org.org_id}_{LEARNER}.json").exists()

    restored = _call(ADMIN1, "POST", "/api/institutions/memberships",
                     json={"org_id": env.org.org_id, "user_id": LEARNER, "role": "LEARNER"})
    assert restored.status_code == 200, restored.text
    roster = _call(TEACHER, "GET", f"/api/institutions/classes/{cid}/roster").json()["roster"]
    assert set(roster) == {LEARNER, LEARNER2}                    # no re-enrollment needed
    assert set(env.projections[cid]["enrolled_learner_ids"]) == {LEARNER, LEARNER2}
    assert _call(TEACHER, "GET", f"/api/classes/{cid}/knowledge-state").status_code == 200


# --- PostgreSQL path (fake repository, no database) ---------------------------

class FakeRepo:
    def __init__(self, memberships):
        self.m = {(x.org_id, x.user_id): x for x in memberships}
        self.calls = []

    async def lock_active_admins(self, conn, org_id):
        self.calls.append("lock_admins")
        return sorted((x for (o, _), x in self.m.items()
                       if o == org_id and x.role == UserRole.ADMIN and x.is_active),
                      key=lambda x: x.membership_id)

    async def get_membership(self, conn, org_id, user_id, *, for_update=False):
        self.calls.append(f"get(for_update={for_update})")
        return self.m.get((org_id, user_id))

    async def deactivate_membership(self, conn, org_id, user_id):
        self.calls.append("deactivate")
        self.m[(org_id, user_id)] = self.m[(org_id, user_id)].model_copy(update={"is_active": False})
        return True


def _pg_service(monkeypatch, tmp_path, repo):
    svc = InstitutionService(base_dir=str(tmp_path / "inst"))
    began = []

    class Tx:
        async def __aenter__(self):
            began.append("begin")

        async def __aexit__(self, *exc):
            began.append("rollback" if exc[0] else "commit")
            return False

    class Conn:
        def transaction(self):
            return Tx()

    class Acquire:
        async def __aenter__(self):
            return Conn()

        async def __aexit__(self, *exc):
            return False

    async def pool():
        return SimpleNamespace(acquire=lambda: Acquire())

    class FakeAudit:
        def __init__(self):
            self.events = []

        async def insert(self, conn, **event):
            self.events.append(event)

    async def staff_ok(_conn, _user_id):
        return None  # provisioning has its own tests (JSON mode and live PostgreSQL)

    svc._pg_enabled, svc._repo, svc._pool = True, repo, pool
    svc._audit_repo = FakeAudit()
    svc._pg_require_provisioned_staff = staff_ok
    return svc, began


def _mem(org, user, role, active=True):
    return OrgMembership(membership_id=f"mem_{user}", org_id=org, user_id=user, role=role, is_active=active)


def test_pg_deactivation_locks_admins_first_inside_one_transaction(monkeypatch, tmp_path):
    repo = FakeRepo([_mem("o", "a1", UserRole.ADMIN), _mem("o", "a2", UserRole.ADMIN),
                     _mem("o", "t1", UserRole.TEACHER)])
    svc, tx = _pg_service(monkeypatch, tmp_path, repo)
    membership, changed = asyncio.run(svc._pg_deactivate_membership("o", "a1", "t1"))
    assert changed and membership.is_active is False
    assert repo.calls == ["lock_admins", "get(for_update=True)", "deactivate"]
    assert tx == ["begin", "commit"]


def test_pg_last_admin_is_refused_and_rolls_back_without_writing(monkeypatch, tmp_path):
    repo = FakeRepo([_mem("o", "a1", UserRole.ADMIN), _mem("o", "t1", UserRole.TEACHER)])
    svc, tx = _pg_service(monkeypatch, tmp_path, repo)
    with pytest.raises(LastAdminError):
        asyncio.run(svc._pg_deactivate_membership("o", "a1", "a1"))
    assert "deactivate" not in repo.calls and tx == ["begin", "rollback"]


def test_pg_second_of_two_racing_admin_deactivations_sees_committed_state(monkeypatch, tmp_path):
    """Models the lock hand-off: after the first commit the second locks only what
    is still active, so it is either unauthorized or refused as last admin."""
    repo = FakeRepo([_mem("o", "a1", UserRole.ADMIN), _mem("o", "a2", UserRole.ADMIN)])
    svc, _ = _pg_service(monkeypatch, tmp_path, repo)
    asyncio.run(svc._pg_deactivate_membership("o", "a1", "a2"))      # first wins
    with pytest.raises(AuthorizationError):                          # a2 no longer admin
        asyncio.run(svc._pg_deactivate_membership("o", "a2", "a1"))
    with pytest.raises(LastAdminError):                              # a1 is the last one
        asyncio.run(svc._pg_deactivate_membership("o", "a1", "a1"))


def test_pg_non_admin_missing_and_inactive_cases(monkeypatch, tmp_path):
    repo = FakeRepo([_mem("o", "a1", UserRole.ADMIN), _mem("o", "t1", UserRole.TEACHER),
                     _mem("o", "l1", UserRole.LEARNER, active=False)])
    svc, _ = _pg_service(monkeypatch, tmp_path, repo)
    with pytest.raises(AuthorizationError):
        asyncio.run(svc._pg_deactivate_membership("o", "t1", "a1"))
    with pytest.raises(MembershipNotFoundError):
        asyncio.run(svc._pg_deactivate_membership("o", "a1", "ghost"))
    _, changed = asyncio.run(svc._pg_deactivate_membership("o", "a1", "l1"))
    assert changed is False and "deactivate" not in repo.calls


class SqlConn:
    def __init__(self):
        self.sql = []

    async def fetch(self, sql, *args):
        self.sql.append(sql)
        return []


def test_repository_queries_lock_admins_and_filter_active_learners():
    conn, repo = SqlConn(), InstitutionRepository()
    asyncio.run(repo.lock_active_admins(conn, "o"))
    asyncio.run(repo.get_active_class_learner_ids(conn, "c"))
    lock_sql, roster_sql = (" ".join(s.split()) for s in conn.sql)
    assert "role = 'ADMIN'" in lock_sql and "is_active = TRUE" in lock_sql
    assert "ORDER BY membership_id FOR UPDATE" in lock_sql
    assert "m.is_active = TRUE" in roster_sql and "m.role = 'LEARNER'" in roster_sql
    assert "JOIN org_memberships" in roster_sql


# --- Last-active-admin invariant on role changes (POST /institutions/memberships) ---

def _set_role(env, caller, target, role, org_id=None):
    return _call(caller, "POST", "/api/institutions/memberships",
                 json={"org_id": org_id or env.org.org_id, "user_id": target, "role": role})


def _role(env, user):
    return env.svc.get_membership(env.org.org_id, user).role


def test_last_active_admin_cannot_demote_themselves(env):
    assert _deactivate(env, ADMIN1, ADMIN2).status_code == 200      # ADMIN1 is the only admin
    response = _set_role(env, ADMIN1, ADMIN1, "TEACHER")
    assert response.status_code == 409, response.text
    assert _role(env, ADMIN1) == UserRole.ADMIN


def test_admin_can_demote_themselves_when_another_active_admin_exists(env):
    response = _set_role(env, ADMIN1, ADMIN1, "TEACHER")
    assert response.status_code == 200, response.text
    assert _role(env, ADMIN1) == UserRole.TEACHER
    # ADMIN1 lost admin rights at once; ADMIN2 remains the organization's admin.
    assert _set_role(env, ADMIN1, LEARNER2, "TEACHER").status_code == 403
    assert _role(env, ADMIN2) == UserRole.ADMIN


def test_demoting_the_other_admin_then_the_last_one_is_blocked(env):
    assert _set_role(env, ADMIN1, ADMIN2, "TEACHER").status_code == 200
    assert _set_role(env, ADMIN1, ADMIN1, "LEARNER").status_code == 409
    assert _deactivate(env, ADMIN1, ADMIN1).status_code == 409      # same invariant, other path
    assert _role(env, ADMIN1) == UserRole.ADMIN


def test_membership_creation_promotion_and_reactivation_still_work(env):
    new_user = str(uuid.uuid4())
    asyncio.run(env.svc.users.ensure_user(new_user, None))
    assert _set_role(env, ADMIN1, new_user, "TEACHER").status_code == 200       # create
    assert _role(env, TEACHER) == UserRole.TEACHER
    assert _set_role(env, ADMIN1, TEACHER, "ADMIN").status_code == 200           # promote
    assert _role(env, TEACHER) == UserRole.ADMIN
    assert _set_role(env, ADMIN1, ADMIN1, "ADMIN").status_code == 200            # no-op re-add

    assert _deactivate(env, ADMIN1, ADMIN2).status_code == 200
    assert not _active(env, ADMIN2)
    assert _set_role(env, ADMIN1, ADMIN2, "ADMIN").status_code == 200            # reactivate
    assert _active(env, ADMIN2) and _role(env, ADMIN2) == UserRole.ADMIN


def test_non_admin_and_cross_org_cannot_change_roles(env):
    assert _set_role(env, TEACHER, LEARNER2, "TEACHER").status_code == 403
    assert _set_role(env, ADMIN_B, ADMIN1, "TEACHER").status_code == 403
    assert _role(env, ADMIN1) == UserRole.ADMIN


# --- PostgreSQL path: invariant and lock ordering (fake repository) ---------------

class RecordingRepo(FakeRepo):
    """FakeRepo that also records lock requests and supports the upsert."""

    async def lock_active_admins(self, conn, org_id):
        admins = await super().lock_active_admins(conn, org_id)
        self.calls.append(("admins", [a.membership_id for a in admins]))
        return admins

    async def get_membership(self, conn, org_id, user_id, *, for_update=False):
        if for_update:
            self.calls.append(("target", user_id))
        return self.m.get((org_id, user_id))

    async def create_membership(self, conn, *, membership_id, org_id, user_id, role):
        self.calls.append(("upsert", user_id, role))
        self.m[(org_id, user_id)] = _mem(org_id, user_id, role)
        return self.m[(org_id, user_id)]


def _lock_events(repo):
    return [c for c in repo.calls if isinstance(c, tuple) and c[0] in ("admins", "target")]


def test_pg_role_change_refuses_to_demote_the_last_admin(monkeypatch, tmp_path):
    repo = RecordingRepo([_mem("o", "a1", UserRole.ADMIN), _mem("o", "t1", UserRole.TEACHER)])
    svc, tx = _pg_service(monkeypatch, tmp_path, repo)
    with pytest.raises(LastAdminError):
        asyncio.run(svc._pg_add_membership_as_admin("m", "o", "a1", "a1", UserRole.TEACHER))
    assert not any(c[0] == "upsert" for c in repo.calls if isinstance(c, tuple))
    assert tx == ["begin", "rollback"]
    assert repo.m[("o", "a1")].role == UserRole.ADMIN


def test_pg_role_change_allows_demotion_when_another_admin_exists(monkeypatch, tmp_path):
    repo = RecordingRepo([_mem("o", "a1", UserRole.ADMIN), _mem("o", "a2", UserRole.ADMIN)])
    svc, tx = _pg_service(monkeypatch, tmp_path, repo)
    result = asyncio.run(svc._pg_add_membership_as_admin("m", "o", "a1", "a1", UserRole.TEACHER))
    assert result.role == UserRole.TEACHER and tx == ["begin", "commit"]
    # ...and the org still has exactly one active admin afterwards.
    with pytest.raises(LastAdminError):
        asyncio.run(svc._pg_add_membership_as_admin("m", "o", "a2", "a2", UserRole.LEARNER))


def test_pg_role_change_authorization_and_reactivation(monkeypatch, tmp_path):
    repo = RecordingRepo([_mem("o", "a1", UserRole.ADMIN), _mem("o", "t1", UserRole.TEACHER),
                          _mem("o", "t2", UserRole.TEACHER, active=False)])
    svc, _ = _pg_service(monkeypatch, tmp_path, repo)
    with pytest.raises(AuthorizationError):                         # non-admin
        asyncio.run(svc._pg_add_membership_as_admin("m", "o", "t1", "t1", UserRole.ADMIN))
    with pytest.raises(AuthorizationError):                         # wrong org
        asyncio.run(svc._pg_add_membership_as_admin("m", "other", "a1", "t1", UserRole.TEACHER))
    reactivated = asyncio.run(
        svc._pg_add_membership_as_admin("m", "o", "a1", "t2", UserRole.TEACHER)
    )
    assert reactivated.is_active


def test_pg_add_and_deactivate_use_the_same_lock_order(monkeypatch, tmp_path):
    """Both operations take the active-admin set (ascending membership_id) first and
    the target row second, so neither can hold a row the other needs in reverse order.
    This checks the acquisition sequence against a fake; it is not a concurrency test."""
    members = [_mem("o", "a1", UserRole.ADMIN), _mem("o", "a2", UserRole.ADMIN),
               _mem("o", "t1", UserRole.TEACHER)]
    sequences = {}
    for name, op in (
        ("add", lambda s: s._pg_add_membership_as_admin("m", "o", "a1", "a2", UserRole.TEACHER)),
        ("deactivate", lambda s: s._pg_deactivate_membership("o", "a1", "t1")),
    ):
        repo = RecordingRepo(list(members))
        svc, _ = _pg_service(monkeypatch, tmp_path, repo)
        asyncio.run(op(svc))
        sequences[name] = _lock_events(repo)

    for name, events in sequences.items():
        kinds = [e[0] for e in events]
        assert kinds == ["admins", "target"], (name, events)
        admin_ids = events[0][1]
        assert admin_ids == sorted(admin_ids), (name, admin_ids)
    assert sequences["add"][0] == sequences["deactivate"][0]       # identical admin lock set/order

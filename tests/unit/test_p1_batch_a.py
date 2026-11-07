"""P1 Batch A: document-access query path (F1), event-loop safety (F2), usage factory
(F3), explicit runtime environment (S4), class-scoped 404 code (F7).

Unit and JSON-mode tests (tmp_path only). The PostgreSQL behavior of F1/F3 is
covered by tests/integration/test_p1_postgres_live.py on a disposable database.
"""

from __future__ import annotations

import ast
import asyncio
import threading
import uuid
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from backend import config
from backend.routes import api as api_route
from backend.services.document_access import DocumentAccessService

REPO = Path(__file__).resolve().parents[2]


# --- F1: DocumentAccessService takes the SQL path when the store supports it ----------------

class _SqlShares:
    supports_learner_access_queries = True

    def __init__(self, owned, shared, exists=True):
        self.owned, self.shared, self.exists = set(owned), set(shared), exists
        self.calls = []

    def owned_and_shared_document_ids(self, user_id):
        self.calls.append(("owned_and_shared", user_id))
        return set(self.owned), set(self.shared)

    def learner_has_shared_access(self, document_id, user_id):
        self.calls.append(("exists", document_id, user_id))
        return self.exists

    def list_all(self):
        raise AssertionError("PostgreSQL mode must not scan every share")

    def list_for_document(self, document_id):
        raise AssertionError("PostgreSQL mode must not loop over grants")


def _service(shares, owner="owner", provisioned=True):
    ownership = SimpleNamespace(get_owner=lambda doc: owner, list_owned_document_ids=lambda u: set())
    institutions = SimpleNamespace(is_provisioned_learner=lambda u: provisioned)
    return DocumentAccessService(ownership=ownership, shares=shares, institutions=institutions)


def test_sql_path_answers_accessible_ids_in_one_call_without_scanning_shares():
    shares = _SqlShares(owned={"doc_own"}, shared={"doc_shared"})
    assert _service(shares).accessible_document_ids("learner") == {"doc_own", "doc_shared"}
    assert shares.calls == [("owned_and_shared", "learner")]


def test_sql_path_keeps_the_provenance_requirement_for_shared_documents():
    shares = _SqlShares(owned={"doc_own"}, shared={"doc_shared"})
    assert _service(shares, provisioned=False).accessible_document_ids("learner") == {"doc_own"}
    assert _service(shares, provisioned=False).can_read("doc_shared", "learner") is False


def test_sql_path_can_read_owner_shortcut_and_exists_check():
    shares = _SqlShares(owned=(), shared=(), exists=True)
    service = _service(shares, owner="owner")
    assert service.can_read("doc", "owner") is True and shares.calls == []          # owner: no share query
    assert service.can_read("doc", "learner") is True
    assert shares.calls == [("exists", "doc", "learner")]
    assert _service(_SqlShares((), (), exists=False)).can_read("doc", "learner") is False
    assert _service(_SqlShares((), ()), owner=None).can_read("doc", "learner") is False   # ownerless


def test_learner_query_is_driven_by_the_callers_enrollments():
    """The SQL starts from the learner's own active enrollments, so unrelated tenants'
    shares are never read, and it encodes the full policy."""
    from backend.repositories.platform_repository import DocumentAccessRepository

    seen = []

    class Conn:
        async def fetch(self, sql, *args):
            seen.append((" ".join(sql.split()), args))
            return []

        async def fetchval(self, sql, *args):
            seen.append((" ".join(sql.split()), args))
            return False

    repo = DocumentAccessRepository()
    asyncio.run(repo.owned_and_shared_document_ids(Conn(), "L"))
    asyncio.run(repo.learner_has_shared_access(Conn(), "D", "L"))
    union_sql, union_args = seen[0]
    exists_sql, exists_args = seen[1]
    for sql in (union_sql, exists_sql):
        assert "FROM class_enrollments AS e" in sql
        assert "WHERE e.learner_id = $1 AND e.status = 'active'" in sql
        assert "m.is_active = TRUE AND m.role = 'LEARNER'" in sql
        assert "o.owner_id = s.owner_id" in sql
        assert "document_shares" in sql and "list_all" not in sql
    assert "FROM document_owners WHERE owner_id = $1" in union_sql
    assert union_args == ("L",) and exists_args == ("L", "D") and "s.document_id = $2" in exists_sql


def test_json_mode_document_stores_keep_the_original_algorithm():
    from storage.document_shares import DocumentShareRepository

    assert not getattr(DocumentShareRepository, "supports_learner_access_queries", False)


# --- F2: no synchronous document checks on the event loop ------------------------------

_SYNC_ACCESS_HELPERS = {"_require_owned_uploaded_document", "_accessible_document_ids",
                        "_authorize_teacher_class", "_require_assigned_teacher_class"}


def _inline_sync_calls_in_async_handlers():
    tree = ast.parse((REPO / "backend/routes/api.py").read_text(encoding="utf-8"))
    found = []

    class Visitor(ast.NodeVisitor):
        def __init__(self):
            self.stack = []

        def visit_AsyncFunctionDef(self, node):
            self.stack.append(node.name)
            self.generic_visit(node)
            self.stack.pop()

        def visit_FunctionDef(self, node):
            self.stack.append(None)          # nested sync defs run in the threadpool
            self.generic_visit(node)
            self.stack.pop()

        def visit_Call(self, node):
            if self.stack and self.stack[-1] and isinstance(node.func, ast.Name) \
                    and node.func.id in _SYNC_ACCESS_HELPERS:
                found.append((self.stack[-1], node.func.id, node.lineno))
            self.generic_visit(node)

    Visitor().visit(tree)
    return found


def test_async_handlers_never_call_synchronous_access_checks_inline():
    assert _inline_sync_calls_in_async_handlers() == []


def test_async_document_check_runs_off_the_event_loop_and_keeps_semantics(monkeypatch):
    from fastapi import HTTPException

    observed = []

    def recording_check(document_id, user_id):
        try:
            asyncio.get_running_loop()
            on_loop = True
        except RuntimeError:
            on_loop = False
        observed.append((document_id, user_id, on_loop, threading.get_ident()))
        if document_id == "denied":
            raise HTTPException(status_code=404, detail="Document not found.")

    monkeypatch.setattr(api_route, "_require_owned_uploaded_document", recording_check)

    async def caller():
        loop_thread = threading.get_ident()
        await api_route._require_document_read_access("allowed", "u1")
        with pytest.raises(HTTPException) as denied:
            await api_route._require_document_read_access("denied", "u1")
        return loop_thread, denied.value.status_code

    loop_thread, status = asyncio.run(caller())
    assert status == 404
    assert [(d, u, on_loop) for d, u, on_loop, _t in observed] == [("allowed", "u1", False), ("denied", "u1", False)]
    assert all(thread != loop_thread for *_x, thread in observed)


def test_affected_route_runs_its_document_check_in_the_threadpool(monkeypatch, api_auth):
    from fastapi import HTTPException

    from backend.app import app

    observed = []

    def recording_check(document_id, user_id):
        try:
            asyncio.get_running_loop()
            observed.append("on-event-loop")
        except RuntimeError:
            observed.append("threadpool")
        raise HTTPException(status_code=404, detail="Document not found.")

    monkeypatch.setattr(api_route, "_require_owned_uploaded_document", recording_check)
    api_auth.login(str(uuid.uuid4()))
    response = TestClient(app).get("/api/subjects/doc_x/concepts/c1/content")
    assert response.status_code == 404 and response.json()["detail"] == "Document not found."
    assert observed == ["threadpool"]


# --- F3: shared usage-service factory ----------------------------------------------------

@pytest.fixture
def usage_factory(tmp_path, monkeypatch):
    from backend.services import usage_service

    monkeypatch.setattr(usage_service, "DEFAULT_JSON_DIR", str(tmp_path / "usage"))
    usage_service.reset_usage_service_for_testing(None)
    yield usage_service
    usage_service.reset_usage_service_for_testing(None)


def test_factory_returns_one_shared_json_instance_wired_to_institution_membership(usage_factory, monkeypatch):
    members = {("org_a", "member")}
    monkeypatch.setattr(api_route, "institution_service", SimpleNamespace(
        get_membership=lambda org, user: SimpleNamespace(is_active=True) if (org, user) in members else None))
    first, second = usage_factory.get_usage_service(), usage_factory.get_usage_service()
    assert first is second and first._pg_enabled is False
    assert asyncio.run(first.record_usage("org_a", "member", "test.units", 1, "t", "r1"))["created"]
    from phase3.errors import AuthorizationError
    with pytest.raises(AuthorizationError):
        asyncio.run(first.record_usage("org_a", "stranger", "test.units", 1, "t", "r2"))


def test_factory_lookup_follows_the_api_institution_store_at_call_time(usage_factory, monkeypatch):
    usage = usage_factory.get_usage_service()
    monkeypatch.setattr(api_route, "institution_service",
                        SimpleNamespace(get_membership=lambda org, user: SimpleNamespace(is_active=True)))
    assert asyncio.run(usage.record_usage("org_b", "u", "test.units", 1, "t", "r3"))["created"]


def test_factory_uses_postgresql_when_configured(usage_factory, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://placeholder@127.0.0.1:9/never")
    usage = usage_factory.get_usage_service()
    assert usage._pg_enabled is True    # construction only; no connection is attempted here


# --- S4: explicit environment, fail closed ---------------------------------------------

@pytest.mark.parametrize("value,fragment", [
    (None, "must be set explicitly"),
    ("", "must be set explicitly"),
    ("prod", "must be one of"),
    ("Production ", None),           # normalized: valid name, then strict checks apply
])
def test_unset_or_unknown_environment_fails_startup(monkeypatch, value, fragment):
    import backend.app as appmod

    monkeypatch.setattr(appmod, "_run_startup_preflight", lambda: {})
    if value is None:
        monkeypatch.delenv("LEARNSENSE_ENV", raising=False)
    else:
        monkeypatch.setenv("LEARNSENSE_ENV", value)
    for key in ("SUPABASE_URL", "SUPABASE_PUBLISHABLE_KEY", "SUPABASE_ANON_KEY", "ALLOWED_ORIGINS"):
        monkeypatch.delenv(key, raising=False)
    with pytest.raises(config.ConfigurationError) as info:
        asyncio.run(appmod.on_startup())
    if fragment:
        assert fragment in str(info.value)
    else:
        assert "SUPABASE_URL is required" in str(info.value)


@pytest.mark.parametrize("name", ["development", "test"])
def test_development_and_test_environments_start_without_production_settings(monkeypatch, name):
    import backend.app as appmod

    monkeypatch.setattr(appmod, "_run_startup_preflight", lambda: {})
    monkeypatch.setattr(appmod, "_preflight_results", {})
    monkeypatch.setenv("LEARNSENSE_ENV", name)
    monkeypatch.delenv("SUPABASE_URL", raising=False)
    monkeypatch.setenv("LEARNSENSE_REQUIRE_PG", "0")
    asyncio.run(appmod.on_startup())     # must not raise


@pytest.mark.parametrize("value", [None, "staging", "production", "bogus"])
def test_demo_and_debug_details_hidden_unless_development_or_test(monkeypatch, value):
    import backend.app as appmod
    from backend.app import app

    monkeypatch.setattr(appmod, "_preflight_results", {"ocr": {"status": "FAILED", "reason": "C:\\x\\y"}})
    if value is None:
        monkeypatch.delenv("LEARNSENSE_ENV", raising=False)
    else:
        monkeypatch.setenv("LEARNSENSE_ENV", value)
    client = TestClient(app)
    assert client.get("/api/auth/personas").status_code == 404
    assert client.get("/api/system/feature-status").json() == {"subsystems": {"ocr": {"status": "FAILED"}}}
    health = client.get("/api/health").json()
    assert set(health) == {"status", "llm_ready"}


def test_development_still_shows_details(monkeypatch):
    from backend.app import app

    monkeypatch.setenv("LEARNSENSE_ENV", "development")
    client = TestClient(app)
    assert client.get("/api/auth/personas").status_code == 200
    assert "llm" in client.get("/api/health").json()

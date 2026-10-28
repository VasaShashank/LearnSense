import hashlib
import sqlite3
import uuid
from types import SimpleNamespace

from fastapi.testclient import TestClient

from backend.app import app
from backend.auth import AuthenticatedUser, get_current_user
from backend.routes import documents as documents_route
from backend.routes import api as api_route
from storage.db import DatabaseManager
from storage.document_ownership import DocumentOwnershipRepository
from storage.job_repository import JobRepository


OWNER = "verified-owner-id"
OTHER = "different-verified-user"


def _as_user(user_id):
    app.dependency_overrides[get_current_user] = lambda: AuthenticatedUser(
        id=user_id, email=None
    )


def _clear_user():
    app.dependency_overrides.pop(get_current_user, None)


def test_document_endpoints_reject_missing_authentication():
    response = TestClient(app).get("/documents/doc_legacy/status")
    assert response.status_code == 401


def test_source_job_endpoints_reject_missing_authentication():
    response = TestClient(app).get("/api/sources/upload/status/job-legacy")
    assert response.status_code == 401


def test_document_owner_can_read_structured_content(monkeypatch, tmp_path):
    repo = DocumentOwnershipRepository(str(tmp_path / "owners"))
    document_id = f"doc_{uuid.uuid4().hex}"
    repo.claim(document_id, OWNER)
    monkeypatch.setattr(documents_route, "ownership", repo)
    monkeypatch.setattr(
        documents_route.storage,
        "load_structured_document",
        lambda _doc_id: {"document_id": document_id, "private": True},
    )
    _as_user(OWNER)
    try:
        response = TestClient(app).get(f"/documents/{document_id}/structured")
    finally:
        _clear_user()
    assert response.status_code == 200
    assert response.json()["private"] is True


def test_new_document_upload_records_verified_owner(monkeypatch, tmp_path):
    repo = DocumentOwnershipRepository(str(tmp_path / "owners"))
    seen = {}
    monkeypatch.setattr(documents_route, "ownership", repo)
    monkeypatch.setattr(documents_route.db, "find_cached_document", lambda **_kw: None)
    monkeypatch.setattr(
        documents_route.input_validator,
        "validate_file",
        lambda *_args: SimpleNamespace(is_valid=True, errors=[]),
    )

    class FakePipeline:
        @staticmethod
        def owner_scoped_cache_key(owner_id, sha256):
            return "scoped-key"

        @staticmethod
        def process_pdf_bytes(**kwargs):
            seen.update(kwargs)
            return SimpleNamespace(
                metadata=SimpleNamespace(
                    processing_status=SimpleNamespace(value="completed"), page_count=1
                )
            )

    monkeypatch.setattr(documents_route, "pipeline", FakePipeline())
    monkeypatch.setattr(
        documents_route.db,
        "get_document_job",
        lambda _doc_id: {"created_at": "now", "owner_id": OWNER},
    )
    _as_user(OWNER)
    try:
        response = TestClient(app).post(
            "/documents",
            files={"file": ("private.pdf", b"fake-pdf", "application/pdf")},
        )
    finally:
        _clear_user()

    assert response.status_code == 202, response.text
    document_id = response.json()["document_id"]
    assert repo.get_owner(document_id) == OWNER
    assert seen["owner_id"] == OWNER
    assert seen["document_id"] == document_id


def test_document_cache_lookup_is_owner_scoped_and_owner_checked(monkeypatch, tmp_path):
    repo = DocumentOwnershipRepository(str(tmp_path / "owners"))
    cached_id = f"doc_{uuid.uuid4().hex}"
    repo.claim(cached_id, OWNER)
    body = b"same uploaded content"
    expected_key = documents_route.pipeline.owner_scoped_cache_key(
        OWNER, documents_route.storage.compute_sha256(body)
    )
    seen = {}
    monkeypatch.setattr(documents_route, "ownership", repo)
    monkeypatch.setattr(
        documents_route.input_validator,
        "validate_file",
        lambda *_args: SimpleNamespace(is_valid=True, errors=[]),
    )

    def find_cached_document(**kwargs):
        seen.update(kwargs)
        return {
            "document_id": cached_id,
            "owner_id": OWNER,
            "status": "completed",
        }

    monkeypatch.setattr(documents_route.db, "find_cached_document", find_cached_document)
    _as_user(OWNER)
    try:
        response = TestClient(app).post(
            "/documents",
            files={"file": ("private.pdf", body, "application/pdf")},
        )
    finally:
        _clear_user()

    assert response.status_code == 202
    assert response.json()["cached"] is True
    assert seen == {"cache_key": expected_key, "owner_id": OWNER}


def test_other_user_and_legacy_ownerless_document_cannot_read_content(monkeypatch, tmp_path):
    repo = DocumentOwnershipRepository(str(tmp_path / "owners"))
    document_id = f"doc_{uuid.uuid4().hex}"
    repo.claim(document_id, OWNER)
    legacy_id = f"doc_{uuid.uuid4().hex}"
    monkeypatch.setattr(documents_route, "ownership", repo)
    monkeypatch.setattr(
        documents_route.storage,
        "load_structured_document",
        lambda _doc_id: (_ for _ in ()).throw(AssertionError("read before auth")),
    )
    _as_user(OTHER)
    try:
        client = TestClient(app)
        cross_user = client.get(f"/documents/{document_id}/structured")
        ownerless = client.get(f"/documents/{legacy_id}/structured")
    finally:
        _clear_user()
    assert cross_user.status_code == 404
    assert ownerless.status_code == 404


def test_private_subject_content_is_uploader_only(monkeypatch, tmp_path):
    owners = DocumentOwnershipRepository(str(tmp_path / "owners"))
    document_id = f"doc_{uuid.uuid4().hex}"
    owners.claim(document_id, OWNER)
    called = []
    monkeypatch.setattr(api_route, "document_ownership", owners)
    monkeypatch.setattr(
        api_route.learning_service,
        "get_concept_learning_content",
        lambda *_args: called.append(True),
    )
    _as_user(OTHER)
    try:
        response = TestClient(app).get(
            f"/api/subjects/{document_id}/concepts/concept-1/content"
        )
    finally:
        _clear_user()
    assert response.status_code == 404
    assert called == []


def test_subject_listing_is_filtered_to_verified_uploader(monkeypatch, tmp_path):
    owners = DocumentOwnershipRepository(str(tmp_path / "owners"))
    owned_id = f"doc_{uuid.uuid4().hex}"
    owners.claim(owned_id, OWNER)
    seen = {}
    monkeypatch.setattr(api_route, "document_ownership", owners)
    monkeypatch.setattr(
        api_route.knowledge_service,
        "list_subjects",
        lambda visible_document_ids=None: seen.update(ids=visible_document_ids) or [],
    )
    _as_user(OWNER)
    try:
        response = TestClient(app).get("/api/subjects")
    finally:
        _clear_user()
    assert response.status_code == 200
    assert seen == {"ids": {owned_id}}


def test_cross_user_cannot_cancel_document_job(monkeypatch, tmp_path):
    repo = DocumentOwnershipRepository(str(tmp_path / "owners"))
    document_id = f"doc_{uuid.uuid4().hex}"
    repo.claim(document_id, OWNER)
    touched = []
    monkeypatch.setattr(documents_route, "ownership", repo)
    monkeypatch.setattr(documents_route.db, "get_document_job", lambda _id: touched.append("read"))
    monkeypatch.setattr(documents_route.db, "update_document_status", lambda *_a: touched.append("write"))
    _as_user(OTHER)
    try:
        response = TestClient(app).post(f"/documents/{document_id}/cancel")
    finally:
        _clear_user()
    assert response.status_code == 404
    assert touched == []


def test_source_job_owner_can_poll_and_other_user_cannot_poll_or_cancel(monkeypatch, tmp_path):
    owners = DocumentOwnershipRepository(str(tmp_path / "owners"))
    jobs = JobRepository(str(tmp_path / "jobs"))
    job_id = str(uuid.uuid4())
    job = jobs.create_job(job_id, "private.pdf", owner_id=OWNER)
    job["document_id"] = "doc_private"
    jobs.save_job(job)
    owners.claim("doc_private", OWNER)
    monkeypatch.setattr(api_route, "document_ownership", owners)
    monkeypatch.setattr(api_route.document_access, "ownership", owners)
    monkeypatch.setattr(api_route, "job_repo", jobs)

    _as_user(OWNER)
    try:
        allowed = TestClient(app).get(f"/api/sources/upload/status/{job_id}")
    finally:
        _clear_user()
    assert allowed.status_code == 200
    assert allowed.json()["filename"] == "private.pdf"

    _as_user(OTHER)
    try:
        client = TestClient(app)
        denied_poll = client.get(f"/api/sources/upload/status/{job_id}")
        denied_cancel = client.post(f"/api/sources/upload/cancel/{job_id}")
    finally:
        _clear_user()
    assert denied_poll.status_code == 404
    assert denied_cancel.status_code == 404
    assert jobs.load_owned_job(job_id, OWNER)["status"] != "cancelled"

    legacy_id = str(uuid.uuid4())
    jobs.create_job(legacy_id, "legacy.pdf")
    _as_user(OTHER)
    try:
        client = TestClient(app)
        legacy_poll = client.get(f"/api/sources/upload/status/{legacy_id}")
        legacy_cancel = client.post(f"/api/sources/upload/cancel/{legacy_id}")
    finally:
        _clear_user()
    assert legacy_poll.status_code == 404
    assert legacy_cancel.status_code == 404
    assert jobs.load_job(legacy_id)["status"] != "cancelled"

    _as_user(OWNER)
    try:
        owner_cancel = TestClient(app).post(f"/api/sources/upload/cancel/{job_id}")
    finally:
        _clear_user()
    assert owner_cancel.status_code == 200
    assert jobs.load_owned_job(job_id, OWNER)["status"] == "cancelled"


def test_new_source_upload_records_document_and_job_owner(monkeypatch, tmp_path):
    owners = DocumentOwnershipRepository(str(tmp_path / "owners"))
    jobs = JobRepository(str(tmp_path / "jobs"))
    monkeypatch.setattr(api_route, "document_ownership", owners)
    monkeypatch.setattr(api_route, "job_repo", jobs)

    class FakeThread:
        def __init__(self, *args, **kwargs):
            pass

        def start(self):
            pass

    monkeypatch.setattr(api_route.threading, "Thread", FakeThread)
    _as_user(OWNER)
    try:
        response = TestClient(app).post(
            "/api/sources/upload",
            files={"file": ("private.pdf", b"private bytes", "application/pdf")},
        )
    finally:
        _clear_user()

    assert response.status_code == 200, response.text
    payload = response.json()
    assert owners.get_owner(payload["document_id"]) == OWNER
    assert jobs.load_owned_job(payload["job_id"], OWNER)["owner_id"] == OWNER


def test_sqlite_document_jobs_store_owner_and_scope_cache(tmp_path):
    db = DatabaseManager(str(tmp_path / "docs.sqlite"))
    sha = hashlib.sha256(b"same content").hexdigest()
    from ingestion.pipeline import IngestionPipeline
    key_a = IngestionPipeline.owner_scoped_cache_key(OWNER, sha)
    key_b = IngestionPipeline.owner_scoped_cache_key(OTHER, sha)
    db.create_document_job("doc_owner_a", sha, "a.pdf", 11, key_a, "completed", owner_id=OWNER)
    db.create_document_job("doc_owner_b", sha, "b.pdf", 11, key_b, "completed", owner_id=OTHER)

    assert db.get_document_job("doc_owner_a")["owner_id"] == OWNER
    assert db.find_cached_document(key_a, owner_id=OWNER)["document_id"] == "doc_owner_a"
    assert db.find_cached_document(key_a, owner_id=OTHER) is None
    assert db.find_cached_document(key_b, owner_id=OWNER) is None


def test_existing_sqlite_documents_upgrade_additively_and_stay_ownerless(tmp_path):
    db_path = tmp_path / "legacy.sqlite"
    with sqlite3.connect(db_path) as connection:
        connection.execute(
            """CREATE TABLE documents (
                document_id TEXT PRIMARY KEY, sha256 TEXT NOT NULL, filename TEXT NOT NULL,
                size_bytes INTEGER NOT NULL, cache_key TEXT UNIQUE, status TEXT NOT NULL,
                page_count INTEGER DEFAULT 0, processed_pages INTEGER DEFAULT 0,
                created_at TEXT NOT NULL, updated_at TEXT NOT NULL
            )"""
        )
        connection.execute(
            "INSERT INTO documents VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            ("doc_legacy", "sha", "legacy.pdf", 5, "old-cache", "completed", 1, 1, "a", "b"),
        )
    db = DatabaseManager(str(db_path))
    assert db.get_document_job("doc_legacy")["owner_id"] is None
    # Reopening proves the local schema update is repeatable.
    assert DatabaseManager(str(db_path)).get_document_job("doc_legacy")["owner_id"] is None


def test_source_listing_filters_ids_before_reading_other_users_content(monkeypatch, tmp_path):
    from backend.services.source_service import SourceService
    from storage.store import DocumentStorage

    root = tmp_path / "docs"
    owned_id = "doc_owned"
    other_id = "doc_other"
    (root / owned_id / "structured").mkdir(parents=True)
    (root / other_id / "structured").mkdir(parents=True)
    service = SourceService(doc_storage=DocumentStorage(str(root)))
    def load_only_owned(doc_id):
        assert doc_id == owned_id
        return {"pages": [], "source": {"filename": "owned.pdf"}}

    monkeypatch.setattr(service.doc_storage, "load_structured_document", load_only_owned)
    SourceService._cached_sources.clear()
    sources = service.list_sources({owned_id}, owner_scope=OWNER)
    assert [source["document_id"] for source in sources] == [owned_id]

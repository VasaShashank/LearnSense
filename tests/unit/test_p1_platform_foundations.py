"""Person 1 platform foundations: configuration, account status, usage/quotas,
job contract, migration runner and service-layer authorization.

Unit and JSON-mode tests. PostgreSQL behavior of the same services is covered by
tests/integration/test_p1_postgres_live.py (disposable database, opt-in).
"""

from __future__ import annotations

import asyncio
import subprocess
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend import config
from backend.api_errors import install_error_handlers
from backend.db import migrations as mig
from backend.repositories import job_store
from backend.services import authorization
from backend.services.usage_service import (
    IdempotencyConflict,
    InvalidUsageError,
    QuotaExceeded,
    UsageService,
    period_bounds,
)
from phase3.errors import AuthorizationError

REPO = Path(__file__).resolve().parents[2]

PROD = {
    "LEARNSENSE_ENV": "production",
    "SUPABASE_URL": "https://example.supabase.co",
    "SUPABASE_PUBLISHABLE_KEY": "sb_publishable_placeholder",
    "DATABASE_URL": "postgresql://user:s3cret@db.internal:5432/app",
    "LEARNSENSE_REQUIRE_PG": "1",
    "ALLOWED_ORIGINS": "https://app.example.edu",
}


# --- Production configuration and CORS ------------------------------------------------

def test_complete_production_config_is_valid():
    assert config.validate_runtime_config(PROD) == []


@pytest.mark.parametrize("key,value,fragment", [
    ("SUPABASE_URL", "", "SUPABASE_URL is required"),
    ("SUPABASE_URL", "http://example.supabase.co", "https"),
    ("SUPABASE_PUBLISHABLE_KEY", "", "SUPABASE_PUBLISHABLE_KEY"),
    ("DATABASE_URL", "", "DATABASE_URL is required"),
    ("LEARNSENSE_REQUIRE_PG", "0", "LEARNSENSE_REQUIRE_PG must be 1"),
    ("ALLOWED_ORIGINS", "", "ALLOWED_ORIGINS must list"),
    ("ALLOWED_ORIGINS", "*", "must not contain '*'"),
    ("ALLOWED_ORIGINS", "http://app.example.edu", "https in production"),
    ("ALLOWED_ORIGINS", "https://app.example.edu/path", "scheme://host"),
    ("LEARNSENSE_TEST_HARNESS", "1", "LEARNSENSE_TEST_HARNESS"),
])
def test_production_config_problems_name_settings_never_values(key, value, fragment):
    env = {**PROD, key: value}
    problems = config.validate_runtime_config(env)
    assert any(fragment in p for p in problems), problems
    joined = " ".join(problems)
    assert "s3cret" not in joined and "placeholder" not in joined


def test_staging_is_strict_but_allows_http_origins_and_development_is_permissive():
    staging = {**PROD, "LEARNSENSE_ENV": "staging", "ALLOWED_ORIGINS": "http://staging.internal:8080"}
    assert config.validate_runtime_config(staging) == []
    assert config.validate_runtime_config({"LEARNSENSE_ENV": "development"}) == []
    assert config.validate_runtime_config({"LEARNSENSE_ENV": "test"}) == []
    assert config.validate_runtime_config({"LEARNSENSE_ENV": "prod"})  # unknown name rejected


def test_anon_key_is_accepted_instead_of_publishable_key():
    env = {**PROD, "SUPABASE_PUBLISHABLE_KEY": "", "SUPABASE_ANON_KEY": "anon"}
    assert config.validate_runtime_config(env) == []


def test_cors_never_combines_wildcard_with_credentials():
    dev = {"LEARNSENSE_ENV": "development"}
    assert config.cors_settings(dev) == (config.DEV_DEFAULT_ORIGINS, True)
    assert config.cors_settings({**dev, "ALLOWED_ORIGINS": "*"}) == (["*"], False)
    assert config.cors_settings({**dev, "ALLOWED_ORIGINS": "https://a.test, https://b.test"}) == (
        ["https://a.test", "https://b.test"], True)
    assert config.cors_settings({}) == ([], False)            # unset environment: no default origins
    assert config.cors_settings({"LEARNSENSE_ENV": "production", "ALLOWED_ORIGINS": "*"}) == ([], False)
    assert config.cors_settings({"LEARNSENSE_ENV": "production"}) == ([], False)


def test_startup_fails_clearly_in_production_without_required_settings(monkeypatch):
    import backend.app as appmod

    monkeypatch.setattr(appmod, "_run_startup_preflight", lambda: {})
    monkeypatch.setenv("LEARNSENSE_ENV", "production")
    for key in ("SUPABASE_URL", "SUPABASE_PUBLISHABLE_KEY", "SUPABASE_ANON_KEY", "ALLOWED_ORIGINS"):
        monkeypatch.delenv(key, raising=False)
    with pytest.raises(config.ConfigurationError) as info:
        asyncio.run(appmod.on_startup())
    message = str(info.value)
    assert "SUPABASE_URL is required" in message and "DATABASE_URL is required" in message


def test_demo_personas_and_status_reasons_are_hidden_in_strict_environments(monkeypatch):
    import backend.app as appmod
    from backend.app import app

    monkeypatch.setattr(appmod, "_preflight_results", {"ocr": {"status": "FAILED", "reason": "C:\\secret\\path"}})
    client = TestClient(app)
    assert client.get("/api/auth/personas").status_code == 200
    assert "reason" in client.get("/api/system/feature-status").json()["subsystems"]["ocr"]
    monkeypatch.setenv("LEARNSENSE_ENV", "production")
    assert client.get("/api/auth/personas").status_code == 404
    assert client.get("/api/system/feature-status").json() == {"subsystems": {"ocr": {"status": "FAILED"}}}


# --- Disabled accounts (real authentication dependency, Supabase mocked) -----------------

def _supabase_returns(monkeypatch, user_id):
    from backend import auth

    class FakeClient:
        def __init__(self, *_a, **_k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_exc):
            return False

        async def get(self, *_a, **_k):
            return httpx.Response(200, json={"id": user_id, "email": "u@example.test"})

    monkeypatch.setattr(auth.httpx, "AsyncClient", FakeClient)
    monkeypatch.setenv("SUPABASE_URL", "https://example.supabase.co")
    monkeypatch.setenv("SUPABASE_PUBLISHABLE_KEY", "placeholder")


def test_disabled_account_is_rejected_by_the_authentication_dependency(monkeypatch, isolated_user_records):
    from backend.app import app

    user_id = str(uuid.uuid4())
    _supabase_returns(monkeypatch, user_id)
    client = TestClient(app)
    headers = {"Authorization": "Bearer token"}
    assert client.get("/api/me", headers=headers).status_code == 200          # provisions the record

    asyncio.run(isolated_user_records.set_status(user_id, "disabled", reason="abuse", actor_user_id="operator"))
    for path in ("/api/me", "/api/institutions/organizations", "/api/subjects"):
        response = client.get(path, headers=headers)
        assert response.status_code == 403, path
        assert response.json()["code"] == "ACCOUNT_DISABLED"

    asyncio.run(isolated_user_records.set_status(user_id, "active", reason=None, actor_user_id="operator"))
    assert client.get("/api/me", headers=headers).status_code == 200


def test_account_status_lookup_failure_fails_closed(monkeypatch, isolated_user_records):
    from backend.app import app

    _supabase_returns(monkeypatch, str(uuid.uuid4()))

    async def broken(_user_id):
        raise OSError("database unavailable")

    monkeypatch.setattr(isolated_user_records, "is_disabled", broken)
    response = TestClient(app).get("/api/me", headers={"Authorization": "Bearer token"})
    assert response.status_code == 503 and response.json()["code"] == "ACCOUNT_STATUS_UNAVAILABLE"


def test_user_records_are_idempotent_and_validate_identity(tmp_path):
    from backend.services.user_service import UserService

    users = UserService(base_dir=str(tmp_path / "users"), pg_enabled=False)
    uid = str(uuid.uuid4())
    first = asyncio.run(users.ensure_user(uid, "a@example.test"))
    second = asyncio.run(users.ensure_user(uid, None))
    assert first["created_at"] == second["created_at"] and second["email"] == "a@example.test"
    with pytest.raises(ValueError):
        asyncio.run(users.ensure_user("student_alex", None))
    with pytest.raises(ValueError):
        asyncio.run(users.set_status(uid, "banned", reason=None, actor_user_id="op"))
    assert asyncio.run(users.set_status(str(uuid.uuid4()), "disabled", reason=None, actor_user_id="op")) is None


# --- Usage events and quotas (JSON mode) -------------------------------------------------

ORG, USER, NON_MEMBER = "org_usage", str(uuid.uuid4()), str(uuid.uuid4())


def _usage(tmp_path, now=None):
    def lookup(org_id, user_id):
        return SimpleNamespace(is_active=True) if (org_id, user_id) == (ORG, USER) else None

    clock = (lambda: now) if now else (lambda: datetime.now(timezone.utc))
    return UsageService(base_dir=str(tmp_path / "usage"), membership_lookup=lookup, pg_enabled=False, clock=clock)


def test_record_usage_is_idempotent_and_never_double_counts(tmp_path):
    usage = _usage(tmp_path)
    first = asyncio.run(usage.record_usage(ORG, USER, "test.units", 3, "unit-test", "req-1"))
    replay = asyncio.run(usage.record_usage(ORG, USER, "test.units", 3, "unit-test", "req-1"))
    assert first["created"] is True and replay["created"] is False
    assert replay["event"]["event_id"] == first["event"]["event_id"]
    assert len(usage._json_events()) == 1
    with pytest.raises(IdempotencyConflict):
        asyncio.run(usage.record_usage(ORG, USER, "test.units", 4, "unit-test", "req-1"))


@pytest.mark.parametrize("dimension,quantity,source,request_id", [
    ("Bad Dimension", 1, "s", "r"), ("test.units", 0, "s", "r"), ("test.units", -2, "s", "r"),
    ("test.units", 1.5, "s", "r"), ("test.units", True, "s", "r"), ("test.units", 1, "", "r"),
    ("test.units", 1, "s", ""),
])
def test_invalid_usage_is_rejected(tmp_path, dimension, quantity, source, request_id):
    with pytest.raises(InvalidUsageError):
        asyncio.run(_usage(tmp_path).record_usage(ORG, USER, dimension, quantity, source, request_id))


def test_usage_attribution_requires_active_membership(tmp_path):
    usage = _usage(tmp_path)
    with pytest.raises(AuthorizationError):
        asyncio.run(usage.record_usage(ORG, NON_MEMBER, "test.units", 1, "s", "req-x"))
    # Personal usage (no organization) is attributable to the user and never limited.
    assert asyncio.run(usage.consume(None, NON_MEMBER, "test.units", 10**6, "s", "req-y"))["created"]


def test_no_plan_means_no_limits_and_limits_are_enforced_per_period(tmp_path):
    now = datetime(2026, 3, 15, 12, 0, tzinfo=timezone.utc)
    usage = _usage(tmp_path, now)
    assert asyncio.run(usage.check_quota(ORG, USER, "test.units", 10**9))["limits"] == []

    asyncio.run(usage.create_plan("starter", "Starter"))
    asyncio.run(usage.set_quota_limit("starter", "test.units", "day", 5))
    asyncio.run(usage.assign_plan(ORG, "starter", assigned_by="operator"))
    for i in range(5):
        asyncio.run(usage.consume(ORG, USER, "test.units", 1, "s", f"req-{i}"))
    with pytest.raises(QuotaExceeded) as info:
        asyncio.run(usage.consume(ORG, USER, "test.units", 1, "s", "req-5"))
    assert info.value.http_status == 429
    assert info.value.details == {"dimension": "test.units", "period": "day", "limit": 5, "used": 5,
                                  "requested": 1, "resets_at": "2026-03-16T00:00:00+00:00"}
    # A replay of an already-recorded request is not re-checked (no double counting).
    assert asyncio.run(usage.consume(ORG, USER, "test.units", 1, "s", "req-0"))["created"] is False
    with pytest.raises(QuotaExceeded):
        asyncio.run(usage.check_quota(ORG, USER, "test.units", 1))
    # Next day the daily limit resets.
    tomorrow = _usage(tmp_path, datetime(2026, 3, 16, 0, 1, tzinfo=timezone.utc))
    assert asyncio.run(tomorrow.consume(ORG, USER, "test.units", 5, "s", "req-next"))["created"]


def test_period_bounds_use_utc_calendar_boundaries():
    now = datetime(2026, 12, 31, 23, 30, tzinfo=timezone.utc)
    assert period_bounds("day", now) == (datetime(2026, 12, 31, tzinfo=timezone.utc),
                                          datetime(2027, 1, 1, tzinfo=timezone.utc))
    assert period_bounds("month", now) == (datetime(2026, 12, 1, tzinfo=timezone.utc),
                                            datetime(2027, 1, 1, tzinfo=timezone.utc))
    assert period_bounds("total", now) == (None, None)


def test_quota_exceeded_maps_to_429_in_the_standard_envelope():
    app = FastAPI()
    install_error_handlers(app)

    @app.get("/limited")
    def limited():
        raise QuotaExceeded("Usage quota exceeded for this organization.", details={"dimension": "x"})

    response = TestClient(app).get("/limited")
    assert response.status_code == 429
    assert response.json()["error"] == "QUOTA_EXCEEDED" and response.json()["code"] == "QUOTA_EXCEEDED"
    assert "Retry-After" not in response.headers


# --- Job contract (pure rules; persistence is covered against PostgreSQL) -------------------

def test_legacy_job_statuses_map_to_the_canonical_vocabulary():
    assert {k: v.value for k, v in job_store.LEGACY_STATUS_MAP.items()} == {
        "queued": "queued", "processing": "running", "done": "succeeded",
        "error": "failed", "cancelled": "cancelled",
    }
    for legacy in job_store.LEGACY_STATUS_MAP:
        assert job_store.to_legacy_status(job_store.to_canonical_status(legacy)) == legacy
    with pytest.raises(ValueError):
        job_store.to_canonical_status("exploded")


def test_terminal_statuses_cannot_be_left():
    for status in job_store.TERMINAL_STATUSES:
        for target, sources in job_store.ALLOWED_TRANSITIONS.items():
            assert status not in sources, (status, target)


# --- Migration runner -------------------------------------------------------------------

def test_repository_migrations_are_contiguous_and_checksummed():
    found = mig.discover_migrations()
    assert [m.version for m in found] == [f"{i:03d}" for i in range(1, len(found) + 1)]
    assert all(len(m.checksum) == 64 for m in found)


@pytest.mark.parametrize("names,error", [
    (["001_a.sql", "003_c.sql"], "contiguous"),
    (["001_a.sql", "001_b.sql"], "Duplicate"),
    (["001_a.sql", "notes.sql"], "Unrecognized"),
    (["002_b.sql"], "contiguous"),
])
def test_bad_migration_sequences_are_refused(tmp_path, names, error):
    for name in names:
        (tmp_path / name).write_text("SELECT 1;", encoding="utf-8")
    with pytest.raises(mig.MigrationError, match=error):
        mig.discover_migrations(tmp_path)


def test_history_evaluation_detects_unknown_out_of_order_and_modified():
    files = [mig.Migration(v, Path(f"{v}_x.sql"), f"sum{v}") for v in ("001", "002", "003")]
    clean = mig.evaluate(files, {"001": "sum001", "002": None})
    assert clean["applied"] == ["001", "002"] and clean["pending"] == ["003"]
    assert clean["unverified_checksums"] == ["002"] and clean["problems"] == []
    assert mig.evaluate(files, {"001": "sum001", "004": None})["problems"]
    assert "Out-of-order" in mig.evaluate(files, {"001": "sum001", "003": "sum003"})["problems"][0]
    assert "changed" in mig.evaluate(files, {"001": "tampered"})["problems"][0]


def test_migrate_cli_refuses_missing_configuration_and_never_prints_credentials():
    sys.path.insert(0, str(REPO / "scripts"))
    try:
        import migrate
    finally:
        sys.path.pop(0)
    assert migrate.describe_target("postgresql://admin:s3cret@db.internal:6543/app") == \
        "database 'app' on db.internal:6543"
    result = subprocess.run(
        [sys.executable, str(REPO / "scripts" / "migrate.py"), "status", "--dsn-env", "LS_UNSET_FOR_TEST"],
        capture_output=True, text=True, cwd=REPO, timeout=60,
        env={"PATH": "", "SYSTEMROOT": __import__("os").environ.get("SYSTEMROOT", "")},
    )
    assert result.returncode == 2 and "LS_UNSET_FOR_TEST is not set" in result.stderr


# --- Service-layer authorization for teacher analytics ----------------------------------------

def test_teacher_analytics_refuse_calls_without_a_minted_grant():
    calls = []
    svc = SimpleNamespace(get_class_knowledge_state=lambda cid, **k: calls.append(cid) or {"ok": cid})
    analytics = authorization.AuthorizedTeacherAnalytics(lambda: svc)
    course_class = SimpleNamespace(class_id="cls_a", org_id="org_a", subject_id="doc")

    forged = authorization.ClassStaffGrant("cls_a", "org_a", "doc", "intruder")
    for bad in (None, "cls_a", forged, SimpleNamespace(class_id="cls_a", _mint=None)):
        with pytest.raises(AuthorizationError):
            analytics.knowledge_state(bad)
    assert calls == []

    grant = authorization.grant_class_staff_access(course_class, "teacher")
    assert analytics.knowledge_state(grant) == {"ok": "cls_a"}


def test_plan_operations_are_confined_to_the_granted_class():
    plans = {"iv_own": SimpleNamespace(class_id="cls_a"), "iv_other": SimpleNamespace(class_id="cls_b")}
    approved = []
    svc = SimpleNamespace(
        load_intervention_plan=plans.get,
        approve_intervention_plan=lambda **k: approved.append(k["intervention_id"]) or k,
    )
    analytics = authorization.AuthorizedTeacherAnalytics(lambda: svc)
    grant = authorization.grant_class_staff_access(SimpleNamespace(class_id="cls_a", org_id="o", subject_id="d"), "t")
    analytics.approve_plan(grant, "iv_own", None)
    with pytest.raises(LookupError):
        analytics.approve_plan(grant, "iv_other", None)
    assert approved == ["iv_own"]


# --- Persistence convention: atomic replace on Windows ------------------------------------

def test_atomic_replace_retries_transient_windows_sharing_violations(monkeypatch):
    from storage import atomic_replace

    calls, sleeps = [], []

    def flaky_replace(src, dst):
        calls.append((src, dst))
        if len(calls) < 3:
            raise PermissionError(5, "Access is denied")

    monkeypatch.setattr(atomic_replace.os, "replace", flaky_replace)
    atomic_replace.replace_atomically("a.tmp", "a.json", _platform="win32", _sleep=sleeps.append)
    assert len(calls) == 3 and sleeps == [0.01, 0.02]


def test_atomic_replace_is_bounded_and_does_not_mask_other_errors(monkeypatch):
    from storage import atomic_replace

    attempts = []

    def always_denied(src, dst):
        attempts.append(1)
        raise PermissionError(5, "Access is denied")

    monkeypatch.setattr(atomic_replace.os, "replace", always_denied)
    with pytest.raises(PermissionError):
        atomic_replace.replace_atomically("a", "b", _platform="win32", _sleep=lambda _s: None)
    assert len(attempts) == atomic_replace._ATTEMPTS

    def missing(src, dst):
        raise FileNotFoundError(src)

    monkeypatch.setattr(atomic_replace.os, "replace", missing)
    with pytest.raises(FileNotFoundError):
        atomic_replace.replace_atomically("a", "b", _platform="win32", _sleep=lambda _s: None)


def test_atomic_replace_is_plain_os_replace_elsewhere(monkeypatch):
    from storage import atomic_replace

    def denied(src, dst):
        raise PermissionError(13, "denied")

    monkeypatch.setattr(atomic_replace.os, "replace", denied)
    with pytest.raises(PermissionError):
        atomic_replace.replace_atomically("a", "b", _platform="linux", _sleep=lambda _s: pytest.fail("slept"))

"""Route-level authentication sweep.

Every route registered on the application must reject an unauthenticated request
with 401 unless it appears in ``PUBLIC_ROUTES``. The allowlist is exact
(method + path template), so a newly added route is protected-by-default and a
public route that disappears or becomes protected fails loudly.

The sweep proves only that the bearer-token dependency is reached before any
handler logic; it says nothing about resource-level authorization.
"""

import re

import pytest
from fastapi.testclient import TestClient

from backend.app import app
from backend.auth import get_current_user

# Intentionally unauthenticated endpoints. Changing this set is a product decision.
PUBLIC_ROUTES = {
    ("GET", "/"),
    ("GET", "/health"),
    ("GET", "/api/health"),
    ("GET", "/api/system/feature-status"),
    ("GET", "/api/resources/{resource_id}"),
    ("GET", "/api/auth/personas"),
}

_METHODS = {"GET", "POST", "PUT", "PATCH", "DELETE"}


def _registered():
    """Return (method, path_template) for every operation in the OpenAPI schema.

    FastAPI nests included routers, so ``app.routes`` does not list them flat; the
    generated schema is the public, version-stable view of every mounted operation.
    Routes declared with ``include_in_schema=False`` would be invisible here (none
    exist today; ``test_no_route_hidden_from_schema`` guards the router modules).
    """
    seen = set()
    for path, operations in app.openapi()["paths"].items():
        for method in operations:
            if method.upper() in _METHODS:
                seen.add((method.upper(), path))
    return sorted(seen)


ALL_ROUTES = _registered()
PROTECTED_ROUTES = [r for r in ALL_ROUTES if r not in PUBLIC_ROUTES]


def _concrete(path: str) -> str:
    """Fill path parameters with a storage-safe placeholder."""
    return re.sub(r"\{[^}]+\}", "x", path)


@pytest.fixture(autouse=True)
def _no_dependency_override_or_supabase_config(monkeypatch):
    # An override leaked from another test would make every route look public.
    assert get_current_user not in app.dependency_overrides
    monkeypatch.delenv("SUPABASE_URL", raising=False)
    monkeypatch.delenv("SUPABASE_PUBLISHABLE_KEY", raising=False)
    monkeypatch.delenv("SUPABASE_ANON_KEY", raising=False)


def test_sweep_is_not_vacuous():
    assert len(ALL_ROUTES) > 50
    assert len(PROTECTED_ROUTES) > 50


def test_public_allowlist_matches_registered_routes():
    # Every allowlisted entry must still exist so stale entries cannot hide a change.
    registered = set(ALL_ROUTES)
    missing = PUBLIC_ROUTES - registered
    assert not missing, f"Allowlisted public routes no longer registered: {sorted(missing)}"


@pytest.mark.parametrize("method,path", PROTECTED_ROUTES, ids=lambda v: str(v))
def test_protected_route_rejects_missing_token(method, path):
    response = TestClient(app, raise_server_exceptions=False).request(
        method, _concrete(path)
    )
    assert response.status_code == 401, (
        f"{method} {path} returned {response.status_code} without a bearer token"
    )
    assert response.headers.get("www-authenticate", "").lower() == "bearer"


@pytest.mark.parametrize("method,path", PROTECTED_ROUTES, ids=lambda v: str(v))
def test_protected_route_rejects_non_bearer_scheme(method, path):
    response = TestClient(app, raise_server_exceptions=False).request(
        method, _concrete(path), headers={"Authorization": "Basic dXNlcjpwYXNz"}
    )
    assert response.status_code == 401, (
        f"{method} {path} returned {response.status_code} for a Basic credential"
    )


@pytest.mark.parametrize("method,path", PROTECTED_ROUTES[:5], ids=lambda v: str(v))
def test_bearer_without_server_auth_config_fails_closed(method, path):
    """A well-formed bearer must never be accepted when Supabase is unconfigured."""
    response = TestClient(app, raise_server_exceptions=False).request(
        method, _concrete(path), headers={"Authorization": "Bearer not-a-real-token"}
    )
    assert response.status_code == 503


def test_no_route_hidden_from_schema():
    from pathlib import Path

    for module in ("backend/app.py", "backend/routes/api.py", "backend/routes/documents.py"):
        assert "include_in_schema=False" not in Path(module).read_text(encoding="utf-8"), (
            f"{module} hides a route from the schema; the sweep cannot see it"
        )

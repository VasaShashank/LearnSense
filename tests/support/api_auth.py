"""Authenticated API access for tests written before Supabase authentication.

Protected routes derive identity only from a verified bearer token, and learner
identities are canonical Supabase UUIDs. Tests therefore:

* name learners with ``learner_uuid("tag")`` (deterministic UUID per tag),
* act as a user with ``api_auth.login(user_id)`` (overrides ``get_current_user``),
* declare test documents a user may read with ``api_auth.allow(document_id, user)``.

Authorization is NOT bypassed: routes still compare the authenticated identity
with path/body learner IDs and still check document access. ``allow`` only adds
explicit read grants for the test's own fixture documents (which have no uploader
record), exactly like a class-material share would.
"""

from __future__ import annotations

import uuid
from typing import Dict, Optional, Set

_NAMESPACE = uuid.UUID("6f1d8a3e-2c47-4b9e-9a0d-1e5b7c3f2a10")


def learner_uuid(tag: str) -> str:
    """Stable canonical learner ID for a test tag."""
    return str(uuid.uuid5(_NAMESPACE, tag))


class ApiAuth:
    def __init__(self, monkeypatch):
        from backend.app import app
        from backend.auth import AuthenticatedUser, get_current_user
        from backend.routes import api as api_route
        from backend.routes import documents as documents_route

        self._app = app
        self._dependency = get_current_user
        self._user_cls = AuthenticatedUser
        self.user_id: Optional[str] = None
        self._grants: Dict[str, Set[str]] = {}

        access = api_route.document_access
        original_can_read = access.can_read
        original_ids = access.accessible_document_ids
        original_owned = api_route.document_ownership.is_owned_by

        def can_read(document_id, user_id):
            return user_id in self._grants.get(document_id, ()) or original_can_read(document_id, user_id)

        def accessible_document_ids(user_id):
            granted = {doc for doc, users in self._grants.items() if user_id in users}
            return set(original_ids(user_id)) | granted

        def is_owned_by(document_id, user_id):
            return user_id in self._grants.get(document_id, ()) or original_owned(document_id, user_id)

        for target in (access, documents_route.document_access):
            monkeypatch.setattr(target, "can_read", can_read)
            monkeypatch.setattr(target, "accessible_document_ids", accessible_document_ids)
        monkeypatch.setattr(api_route.document_ownership, "is_owned_by", is_owned_by)

    def login(self, user_id: str) -> str:
        """Authenticate subsequent requests as ``user_id`` (a canonical UUID)."""
        uuid.UUID(user_id)
        self.user_id = user_id
        identity = self._user_cls(id=user_id, email=None)
        self._app.dependency_overrides[self._dependency] = lambda: identity
        return user_id

    def logout(self) -> None:
        self.user_id = None
        self._app.dependency_overrides.pop(self._dependency, None)

    def allow(self, document_id: str, *user_ids: str) -> None:
        """Grant read access to a test fixture document."""
        self._grants.setdefault(document_id, set()).update(user_ids)

    def learner(self, tag: str, *documents: str) -> str:
        """Canonical learner for ``tag``, logged in, with read access to ``documents``."""
        user_id = learner_uuid(tag)
        for document_id in documents:
            self.allow(document_id, user_id)
        return self.login(user_id)

"""Document ownership/share stores: PostgreSQL in production, JSON in development.

The PostgreSQL stores expose the same synchronous interface as
``storage.document_ownership.DocumentOwnershipRepository`` and
``storage.document_shares.DocumentShareRepository`` so existing call sites keep
working. There is no dual-write: in PostgreSQL mode the JSON directories are not
written. Existing JSON records are imported once with
``scripts/import_document_access.py``.

Share grants and revocations write their audit event in the same transaction.
"""

from __future__ import annotations

import time
from typing import Any, Dict, List, Optional, Set, Tuple

from backend.services import audit_log
from storage.id_validation import validate_storage_id


def _run(coro_factory):
    from backend.db.pg_connection import get_pg_pool
    from backend.services.institution_service import _run_async

    async def _op():
        pool = await get_pg_pool()
        async with pool.acquire() as conn:
            async with conn.transaction():
                return await coro_factory(conn)

    return _run_async(_op())


class PgDocumentOwnershipRepository:
    def __init__(self):
        from backend.repositories.platform_repository import DocumentAccessRepository

        self._repo = DocumentAccessRepository()
        self._owner_cache: Dict[str, Tuple[float, Optional[str]]] = {}
        self._cache_ttl = 300.0  # 5 minutes

    def claim(self, document_id: str, owner_id: str) -> None:
        """Create owner metadata once; never transfer ownership."""
        validate_storage_id(document_id, name="document_id")
        if not isinstance(owner_id, str) or not owner_id.strip():
            raise ValueError("owner_id is required")
        stored = _run(lambda conn: self._repo.claim(conn, document_id, owner_id))
        if stored != owner_id:
            raise ValueError("Document already has an owner")
        self._owner_cache[document_id] = (time.monotonic() + self._cache_ttl, owner_id)

    def get_owner(self, document_id: str) -> Optional[str]:
        try:
            validate_storage_id(document_id, name="document_id")
        except ValueError:
            return None
        now = time.monotonic()
        cached = self._owner_cache.get(document_id)
        if cached is not None and cached[0] > now:
            return cached[1]
        owner = _run(lambda conn: self._repo.get_owner(conn, document_id))
        self._owner_cache[document_id] = (now + self._cache_ttl, owner)
        return owner

    def is_owned_by(self, document_id: str, owner_id: str) -> bool:
        return self.get_owner(document_id) == owner_id

    def list_owned_document_ids(self, owner_id: str) -> Set[str]:
        return set(_run(lambda conn: self._repo.list_owned(conn, owner_id)))


class PgDocumentShareRepository:
    """Grants are written with an audit event in one transaction."""

    writes_audit = True
    # DocumentAccessService uses the tenant-scoped SQL below instead of list_all().
    supports_learner_access_queries = True

    def __init__(self):
        from backend.repositories.platform_repository import AuditRepository, DocumentAccessRepository

        self._repo = DocumentAccessRepository()
        self._audit = AuditRepository()
        self._shared_cache: Dict[Tuple[str, str], Tuple[float, bool]] = {}
        self._cache_ttl = 300.0  # 5 minutes

    def owned_and_shared_document_ids(self, user_id: str):
        owned, shared = _run(lambda conn: self._repo.owned_and_shared_document_ids(conn, user_id))
        return set(owned), set(shared)

    def learner_has_shared_access(self, document_id: str, user_id: str) -> bool:
        now = time.monotonic()
        key = (document_id, user_id)
        cached = self._shared_cache.get(key)
        if cached is not None and cached[0] > now:
            return cached[1]
        res = _run(lambda conn: self._repo.learner_has_shared_access(conn, document_id, user_id))
        self._shared_cache[key] = (now + self._cache_ttl, res)
        return res

    def grant(self, document_id: str, class_id: str, owner_id: str, shared_by: str) -> Dict[str, Any]:
        validate_storage_id(document_id, name="document_id")
        validate_storage_id(class_id, name="class_id")
        if not owner_id or not shared_by:
            raise ValueError("Verified owner and sharing user are required")

        async def _op(conn) -> Tuple[Dict[str, Any], bool]:
            record, created = await self._repo.grant(
                conn, document_id=document_id, class_id=class_id, owner_id=owner_id, shared_by=shared_by
            )
            if record["owner_id"] != owner_id:
                raise ValueError("Document share owner mismatch")
            if created:
                org_id = await conn.fetchval("SELECT org_id FROM course_classes WHERE class_id = $1", class_id)
                await self._audit.insert(
                    conn, actor_user_id=shared_by, org_id=org_id, action=audit_log.SHARE_GRANTED,
                    target_type="document", target_id=document_id, details={"class_id": class_id},
                )
            return record

        return _run(_op)

    def revoke(self, document_id: str, class_id: str, owner_id: str) -> bool:
        validate_storage_id(class_id, name="class_id")

        async def _op(conn) -> bool:
            revoked = await self._repo.revoke(conn, document_id=document_id, class_id=class_id, owner_id=owner_id)
            if revoked:
                org_id = await conn.fetchval("SELECT org_id FROM course_classes WHERE class_id = $1", class_id)
                await self._audit.insert(
                    conn, actor_user_id=owner_id, org_id=org_id, action=audit_log.SHARE_REVOKED,
                    target_type="document", target_id=document_id, details={"class_id": class_id},
                )
            return revoked

        return _run(_op)

    def list_for_document(self, document_id: str) -> List[Dict[str, Any]]:
        try:
            validate_storage_id(document_id, name="document_id")
        except ValueError:
            return []
        return _run(lambda conn: self._repo.list_for_document(conn, document_id))

    def list_all(self) -> List[Dict[str, Any]]:
        return _run(lambda conn: self._repo.list_all(conn))


def build_document_stores():
    """(ownership, shares) for the configured persistence mode."""
    from backend.db.pg_connection import is_pg_configured

    if is_pg_configured():
        return PgDocumentOwnershipRepository(), PgDocumentShareRepository()
    from storage.document_ownership import DocumentOwnershipRepository
    from storage.document_shares import DocumentShareRepository

    return DocumentOwnershipRepository(), DocumentShareRepository()

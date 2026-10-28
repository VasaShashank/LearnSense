"""Resolve private-document access from ownership or explicit class grants."""

from __future__ import annotations

from typing import Set

from storage.document_ownership import DocumentOwnershipRepository
from storage.document_shares import DocumentShareRepository


class DocumentAccessService:
    def __init__(
        self,
        ownership: DocumentOwnershipRepository,
        shares: DocumentShareRepository,
        institutions,
    ):
        self.ownership = ownership
        self.shares = shares
        self.institutions = institutions

    def can_read(self, document_id: str, user_id: str) -> bool:
        """Return true for the uploader or an actively enrolled class learner."""
        owner_id = self.ownership.get_owner(document_id)
        if owner_id is None:
            return False
        if owner_id == user_id:
            return True

        for grant in self.shares.list_for_document(document_id):
            if grant.get("owner_id") != owner_id:
                continue
            class_id = grant.get("class_id")
            course_class = self.institutions.get_class(class_id)
            if course_class is None:
                continue
            if self.institutions.is_active_learner_enrolled(class_id, user_id):
                return True
        return False

    def accessible_document_ids(self, user_id: str) -> Set[str]:
        """Return owned documents plus current grants for active class learners."""
        visible = self.ownership.list_owned_document_ids(user_id)
        for grant in self.shares.list_all():
            document_id = grant.get("document_id")
            class_id = grant.get("class_id")
            if not isinstance(document_id, str) or not isinstance(class_id, str):
                continue
            owner_id = self.ownership.get_owner(document_id)
            if owner_id is None or grant.get("owner_id") != owner_id:
                continue
            if self.institutions.get_class(class_id) is None:
                continue
            if self.institutions.is_active_learner_enrolled(class_id, user_id):
                visible.add(document_id)
        return visible

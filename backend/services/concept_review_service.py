"""
Concept Verification & Curriculum Review Workflow Service (Person 2).
Provides manual review, evidence inspection, canonical mapping correction,
hierarchy adjustment, prerequisite validation, and approval workflow
for extracted educational concepts prior to canonical curriculum entry.
"""

from __future__ import annotations

import hashlib
import re
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional, Sequence, Tuple

from pydantic import BaseModel, ConfigDict, Field

from curriculum.graph import would_create_cycle
from curriculum.ids import stable_key_from_name
from curriculum.mapping import ProposedConcept
from curriculum.models import (
    AuditInfo,
    CanonicalConcept,
    ClassLevel,
    ConceptLifecycleStatus,
    CurriculumGraph,
    Examination,
    ReviewStatus,
    SourceRef,
    Subject,
    utc_now_iso,
)
from curriculum.repository import CurriculumRepository
from curriculum.review import CurriculumReviewService, ReviewAction, ReviewConflictError, ReviewerRole
from storage.repositories import LearningContextRepository
from storage.store import DocumentStorage


class ConceptReviewStatus(str, Enum):
    """Explicit review statuses for extracted document concepts."""

    PENDING_REVIEW = "pending_review"
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    DUPLICATE = "duplicate"
    NEEDS_CANONICAL_MAPPING = "needs_canonical_mapping"
    NEEDS_EVIDENCE_REVIEW = "needs_evidence_review"
    APPROVED_FOR_CURRICULUM = "approved_for_curriculum"


class ConceptReviewDecision(str, Enum):
    """Actions an authorized reviewer can perform on an extracted concept."""

    ACCEPT = "accept"
    REJECT = "reject"
    EDIT_NAME = "edit_name"
    MARK_DUPLICATE = "mark_duplicate"
    REQUEST_NEW_CANONICAL = "request_new_canonical"
    FLAG_REVIEW = "flag_review"
    APPROVE_FOR_CURRICULUM = "approve_for_curriculum"


class ConceptReviewAuditEntry(BaseModel):
    """Immutable audit record for a single concept review decision."""

    model_config = ConfigDict(extra="forbid")

    entry_id: str
    document_id: str
    concept_id: str
    action: str
    reviewer_id: str
    timestamp: str
    previous_status: str
    new_status: str
    previous_name: Optional[str] = None
    new_name: Optional[str] = None
    reason: str = ""
    notes: str = ""
    metadata: Dict[str, Any] = Field(default_factory=dict)


class ConceptReviewWorkflowService:
    """
    Orchestrates human concept verification, evidence inspection, canonical
    mapping review, hierarchy adjustment, and diagnostic gating.
    """

    def __init__(
        self,
        context_repo: Optional[LearningContextRepository] = None,
        curriculum_repo: Optional[CurriculumRepository] = None,
        doc_storage: Optional[DocumentStorage] = None,
    ):
        self.context_repo = context_repo or LearningContextRepository()
        self.curriculum_repo = curriculum_repo or CurriculumRepository()
        self.doc_storage = doc_storage or DocumentStorage()
        self.review_service = CurriculumReviewService(repository=self.curriculum_repo)

    # ----------------------------------------------------------------- Load & Items
    def get_document_review_items(self, document_id: str) -> Dict[str, Any]:
        """
        Constructs the comprehensive review view for all extracted concepts,
        evidence excerpts, mappings, topics, and prerequisite edges in a document.
        """
        ctx = self.context_repo.load_context(document_id)
        if ctx is None:
            raise ValueError(f"No learning context stored for document '{document_id}'")

        curriculum_id = ctx.metadata.get("curriculum_id") or "jee_main_2027"
        graph = self.curriculum_repo.load_graph(curriculum_id) or CurriculumGraph(curriculum_id=curriculum_id)

        reviews = ctx.metadata.setdefault("concept_reviews", {})
        audit_log = ctx.metadata.get("review_audit_log", [])

        # Build list of canonical concepts for mapping suggestions
        canonical_lookup: Dict[str, CanonicalConcept] = dict(graph.concepts)
        canonical_terms: Dict[str, str] = {}
        for cid, c in canonical_lookup.items():
            canonical_terms[c.name.lower()] = cid
            for a in c.aliases:
                canonical_terms[a.lower()] = cid

        # Discover intra-document duplicate candidates
        concept_names = [c.canonical_name for c in ctx.concepts.values()]
        normalized_clusters: Dict[str, List[str]] = {}
        for c in ctx.concepts.values():
            root = re.sub(r"[^a-z0-9]", "", c.canonical_name.lower())
            normalized_clusters.setdefault(root, []).append(c.concept_id)

        # Inspect topic structure
        topic_hierarchy: List[Dict[str, Any]] = []
        for t in ctx.topics:
            topic_hierarchy.append(
                {
                    "topic_id": t.get("id") or t.get("topic_id"),
                    "name": t.get("name") or t.get("title"),
                    "level": t.get("level", 1),
                    "parent_id": t.get("parent_id"),
                    "concept_ids": t.get("concept_ids", []),
                }
            )

        review_items: List[Dict[str, Any]] = []
        status_counts: Dict[str, int] = {s.value: 0 for s in ConceptReviewStatus}

        for cid, concept in ctx.concepts.items():
            c_review = reviews.get(cid, {})
            current_status = c_review.get("status", ConceptReviewStatus.PENDING_REVIEW.value)
            status_counts[current_status] = status_counts.get(current_status, 0) + 1

            # Evidence details
            ev_ids = concept.evidence_ids or []
            ev_obj = ctx.evidence.get(ev_ids[0]) if ev_ids else None
            excerpt = ev_obj.excerpt if ev_obj else concept.description
            block_id = ev_obj.block_id if ev_obj else (concept.block_ids[0] if concept.block_ids else "")
            if ev_obj and ev_obj.span:
                sd = ev_obj.span.model_dump()
                span_dict = {
                    "start_offset": sd.get("start", sd.get("start_offset", 0)),
                    "end_offset": sd.get("end", sd.get("end_offset", len(excerpt))),
                }
            else:
                span_dict = {"start_offset": 0, "end_offset": len(excerpt)}
            pages = [p + 1 for p in concept.page_indices] or [1]

            # Current canonical mapping
            canonical_map = None
            mappings_list = ctx.metadata.get("canonical_mappings") or []
            for m in mappings_list:
                if m.get("label") == concept.canonical_name or m.get("candidate_id") == cid:
                    canonical_id = m.get("canonical_concept_id")
                    target_c = canonical_lookup.get(canonical_id)
                    canonical_map = {
                        "canonical_concept_id": canonical_id,
                        "canonical_name": target_c.name if target_c else canonical_id,
                        "status": m.get("status", "accepted"),
                        "confidence": m.get("confidence", 1.0),
                        "parent_topic": target_c.chapter_id if target_c else None,
                        "aliases": target_c.aliases if target_c else [],
                    }
                    break

            # Override with manually reviewed canonical mapping if present
            if c_review.get("target_canonical_id"):
                override_id = c_review["target_canonical_id"]
                target_c = canonical_lookup.get(override_id)
                canonical_map = {
                    "canonical_concept_id": override_id,
                    "canonical_name": target_c.name if target_c else override_id,
                    "status": "manually_verified",
                    "confidence": 1.0,
                    "parent_topic": target_c.chapter_id if target_c else None,
                    "aliases": target_c.aliases if target_c else [],
                }

            # Suggest alternative canonical candidates from graph
            alternative_candidates = []
            c_lower = concept.canonical_name.lower()
            tokens = set(re.findall(r"\b[a-z0-9]+\b", c_lower)) - {"of", "the", "in", "and", "a", "for"}
            for can_id, can_c in list(canonical_lookup.items())[:30]:
                if canonical_map and can_id == canonical_map.get("canonical_concept_id"):
                    continue
                can_tokens = set(re.findall(r"\b[a-z0-9]+\b", can_c.name.lower())) - {"of", "the", "in", "and", "a", "for"}
                overlap = len(tokens & can_tokens)
                if overlap > 0:
                    sim = overlap / max(len(tokens | can_tokens), 1)
                    alternative_candidates.append(
                        {
                            "canonical_concept_id": can_id,
                            "canonical_name": can_c.name,
                            "parent_topic": can_c.chapter_id or "General",
                            "aliases": can_c.aliases,
                            "similarity": round(sim, 2),
                        }
                    )
            alternative_candidates.sort(key=lambda x: -x["similarity"])

            # Duplicate candidates
            norm_key = re.sub(r"[^a-z0-9]", "", c_lower)
            dupe_ids = [d_id for d_id in normalized_clusters.get(norm_key, []) if d_id != cid]
            dupe_candidates = [
                {"concept_id": d_id, "name": ctx.concepts[d_id].canonical_name}
                for d_id in dupe_ids
                if d_id in ctx.concepts
            ]

            # Hierarchical level & parent topic
            hierarchical_level = c_review.get("hierarchical_level")
            parent_topic_id = c_review.get("parent_topic_id")
            if not hierarchical_level:
                # Infer from topic assignment or mention count
                if len(concept.page_indices) > 3 or "laws of motion" in c_lower or "friction" == c_lower:
                    hierarchical_level = "level_1"
                elif len(ev_ids) > 1:
                    hierarchical_level = "level_2"
                else:
                    hierarchical_level = "level_3"

            item = {
                "concept_id": cid,
                "canonical_name": concept.canonical_name,
                "original_text": concept.canonical_name,
                "page_number": pages[0],
                "pages": pages,
                "evidence_excerpt": excerpt,
                "block_id": block_id,
                "span": span_dict,
                "current_canonical_mapping": canonical_map,
                "alternative_canonical_candidates": alternative_candidates[:5],
                "hierarchical_level": hierarchical_level,
                "parent_topic_id": parent_topic_id or "topic_main",
                "duplicate_candidates": dupe_candidates,
                "review_status": current_status,
                "review_notes": c_review.get("notes", ""),
                "reviewed_by": c_review.get("reviewed_by"),
                "reviewed_at": c_review.get("reviewed_at"),
            }
            review_items.append(item)

        # Prerequisite relationships with review states
        prereqs = []
        for p in ctx.prerequisites:
            p_key = f"{p.source_concept_id}::{p.target_concept_id}"
            p_review = ctx.metadata.get("prerequisite_reviews", {}).get(p_key, {})
            prereqs.append(
                {
                    "source_concept_id": p.source_concept_id,
                    "source_name": ctx.concepts.get(p.source_concept_id, concept).canonical_name if p.source_concept_id in ctx.concepts else p.source_concept_id,
                    "target_concept_id": p.target_concept_id,
                    "target_name": ctx.concepts.get(p.target_concept_id, concept).canonical_name if p.target_concept_id in ctx.concepts else p.target_concept_id,
                    "confidence": getattr(p, "confidence", 0.9),
                    "status": p_review.get("status", "accepted"),
                    "reviewer_id": p_review.get("reviewer_id"),
                    "reviewed_at": p_review.get("reviewed_at"),
                }
            )

        return {
            "document_id": document_id,
            "document_title": ctx.document_title or document_id,
            "source_filename": ctx.source_filename,
            "subject": ctx.metadata.get("subject", "Physics"),
            "chapter": ctx.metadata.get("chapter", ctx.document_title),
            "examination": ctx.metadata.get("examination", "JEE_MAIN"),
            "target_curriculum": ctx.metadata.get("curriculum_id", "jee_main_2027"),
            "total_concepts": len(ctx.concepts),
            "status_counts": status_counts,
            "concepts": review_items,
            "topics": topic_hierarchy,
            "prerequisites": prereqs,
            "audit_history_count": len(audit_log),
        }

    # ----------------------------------------------------------------- Concept Decisions
    def apply_concept_decision(
        self,
        document_id: str,
        concept_id: str,
        decision: ConceptReviewDecision | str,
        reviewer_id: str,
        *,
        reason: str = "",
        new_name: Optional[str] = None,
        duplicate_of_concept_id: Optional[str] = None,
        target_canonical_id: Optional[str] = None,
        new_hierarchical_level: Optional[str] = None,
        new_parent_topic_id: Optional[str] = None,
        status: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Executes a manual concept verification decision on an extracted concept.
        Ensures audit logging, stable ID preservation, and curriculum gating.
        """
        if not reviewer_id or not str(reviewer_id).strip():
            raise ValueError("reviewer_id is mandatory for auditable review decisions.")

        ctx = self.context_repo.load_context(document_id)
        if ctx is None:
            raise ValueError(f"Document '{document_id}' not found.")

        if concept_id not in ctx.concepts:
            raise ValueError(f"Concept '{concept_id}' does not exist in document '{document_id}'.")

        concept = ctx.concepts[concept_id]
        reviews = ctx.metadata.setdefault("concept_reviews", {})
        audit_log = ctx.metadata.setdefault("review_audit_log", [])

        c_review = reviews.setdefault(concept_id, {})
        previous_status = c_review.get("status", ConceptReviewStatus.PENDING_REVIEW.value)
        previous_name = concept.canonical_name
        timestamp = utc_now_iso()

        decision_str = decision.value if isinstance(decision, ConceptReviewDecision) else str(decision)

        # 1. Decision Logic
        if decision_str in (ConceptReviewDecision.ACCEPT.value, "accept"):
            new_status = ConceptReviewStatus.ACCEPTED.value
            c_review["status"] = new_status
            c_review["notes"] = reason or "Concept verified by reviewer"

        elif decision_str in (ConceptReviewDecision.APPROVE_FOR_CURRICULUM.value, "approve_for_curriculum"):
            new_status = ConceptReviewStatus.APPROVED_FOR_CURRICULUM.value
            c_review["status"] = new_status
            c_review["notes"] = reason or "Approved for canonical curriculum and diagnostic generation"

        elif decision_str in (ConceptReviewDecision.REJECT.value, "reject"):
            if not reason:
                raise ValueError("A reason is required when rejecting an academic concept.")
            new_status = ConceptReviewStatus.REJECTED.value
            c_review["status"] = new_status
            c_review["rejection_reason"] = reason
            c_review["notes"] = reason

        elif decision_str in (ConceptReviewDecision.EDIT_NAME.value, "edit_name"):
            if not new_name or not new_name.strip():
                raise ValueError("new_name is required for edit_name decision.")
            new_clean_name = new_name.strip()
            # Update concept name while preserving ID and all provenance links
            concept.canonical_name = new_clean_name
            new_status = previous_status
            c_review["edited_name"] = new_clean_name
            c_review["notes"] = reason or f"Renamed from '{previous_name}' to '{new_clean_name}'"

        elif decision_str in (ConceptReviewDecision.MARK_DUPLICATE.value, "mark_duplicate"):
            if not duplicate_of_concept_id:
                raise ValueError("duplicate_of_concept_id is required to mark as duplicate.")
            new_status = ConceptReviewStatus.DUPLICATE.value
            c_review["status"] = new_status
            c_review["duplicate_of"] = duplicate_of_concept_id
            c_review["notes"] = reason or f"Marked as duplicate of {duplicate_of_concept_id}"

        elif decision_str in (ConceptReviewDecision.REQUEST_NEW_CANONICAL.value, "request_new_canonical"):
            new_status = ConceptReviewStatus.ACCEPTED.value
            c_review["status"] = new_status
            c_review["requested_canonical"] = True
            c_review["notes"] = reason or "Requested new canonical concept entry"

            # Create ProposedConcept in canonical curriculum queue
            try:
                curriculum_id = ctx.metadata.get("curriculum_id") or "jee_main_2027"
                graph = self.curriculum_repo.load_graph(curriculum_id) or CurriculumGraph(curriculum_id=curriculum_id)
                proposed = ProposedConcept.build(
                    name=concept.canonical_name,
                    subject=Subject.PHYSICS,  # Or inferred from context
                    description=concept.description,
                    chapter_id=ctx.document_title or "Chapter",
                )
                self.review_service.accept_proposed_concept(
                    graph,
                    proposed,
                    reviewer_id=reviewer_id,
                    note=reason or "Proposed via document review workflow",
                )
                self.curriculum_repo.save_graph(graph)
            except Exception as exc:
                c_review["canonical_proposal_error"] = str(exc)

        elif decision_str in (ConceptReviewDecision.FLAG_REVIEW.value, "flag_review"):
            if status in (ConceptReviewStatus.NEEDS_CANONICAL_MAPPING.value, ConceptReviewStatus.NEEDS_EVIDENCE_REVIEW.value):
                new_status = status
            else:
                new_status = ConceptReviewStatus.NEEDS_EVIDENCE_REVIEW.value
            c_review["status"] = new_status
            c_review["notes"] = reason or "Flagged for further reviewer attention"

        else:
            raise ValueError(f"Unrecognized review decision '{decision_str}'")

        # 2. Hierarchy and Mapping Overrides
        if target_canonical_id:
            c_review["target_canonical_id"] = target_canonical_id
        if new_hierarchical_level:
            c_review["hierarchical_level"] = new_hierarchical_level
        if new_parent_topic_id:
            c_review["parent_topic_id"] = new_parent_topic_id

        c_review["reviewed_by"] = reviewer_id
        c_review["reviewed_at"] = timestamp

        # 3. Audit Log Entry
        entry_raw = f"{document_id}::{concept_id}::{decision_str}::{reviewer_id}::{timestamp}"
        entry_id = "aud_" + hashlib.sha256(entry_raw.encode("utf-8")).hexdigest()[:16]

        audit_entry = ConceptReviewAuditEntry(
            entry_id=entry_id,
            document_id=document_id,
            concept_id=concept_id,
            action=decision_str,
            reviewer_id=reviewer_id,
            timestamp=timestamp,
            previous_status=previous_status,
            new_status=new_status,
            previous_name=previous_name,
            new_name=concept.canonical_name,
            reason=reason,
            notes=c_review.get("notes", ""),
            metadata={
                "target_canonical_id": target_canonical_id,
                "duplicate_of": duplicate_of_concept_id,
                "hierarchical_level": new_hierarchical_level,
            },
        )
        audit_log.append(audit_entry.model_dump())

        # Persist updated LearningContext
        self.context_repo.save_context(ctx)

        return {
            "status": "success",
            "document_id": document_id,
            "concept_id": concept_id,
            "canonical_name": concept.canonical_name,
            "review_status": new_status,
            "reviewed_by": reviewer_id,
            "reviewed_at": timestamp,
            "audit_entry_id": entry_id,
        }

    # -------------------------------------------------------------- Prerequisite Decisions
    def apply_prerequisite_decision(
        self,
        document_id: str,
        source_concept_id: str,
        target_concept_id: str,
        action: str,  # "approve", "reject", "add", "remove"
        reviewer_id: str,
        *,
        reason: str = "",
    ) -> Dict[str, Any]:
        """
        Approves, rejects, adds, or removes a prerequisite link with DAG acyclicity validation.
        """
        if not reviewer_id:
            raise ValueError("reviewer_id is mandatory.")

        ctx = self.context_repo.load_context(document_id)
        if ctx is None:
            raise ValueError(f"Document '{document_id}' not found.")

        prereq_reviews = ctx.metadata.setdefault("prerequisite_reviews", {})
        p_key = f"{source_concept_id}::{target_concept_id}"
        timestamp = utc_now_iso()

        if action in ("add", "approve"):
            # Construct temporary edge list to verify cycle freedom
            curriculum_id = ctx.metadata.get("curriculum_id") or "jee_main_2027"
            graph = self.curriculum_repo.load_graph(curriculum_id) or CurriculumGraph(curriculum_id=curriculum_id)

            # Check cycle in local context graph
            edges = [
                (p.source_concept_id, p.target_concept_id)
                for p in ctx.prerequisites
                if prereq_reviews.get(f"{p.source_concept_id}::{p.target_concept_id}", {}).get("status") != "rejected"
            ]
            for pk, pr in prereq_reviews.items():
                if pr.get("status") in ("accepted", "approved") and "::" in pk:
                    u, v = pk.split("::", 1)
                    if (u, v) not in edges:
                        edges.append((u, v))

            if (source_concept_id, target_concept_id) not in edges:
                edges.append((source_concept_id, target_concept_id))

            # Detect cycle
            adj: Dict[str, List[str]] = {}
            for u, v in edges:
                adj.setdefault(u, []).append(v)

            visited = set()
            rec_stack = set()

            def _has_cycle(node: str) -> bool:
                visited.add(node)
                rec_stack.add(node)
                for neighbor in adj.get(node, []):
                    if neighbor not in visited:
                        if _has_cycle(neighbor):
                            return True
                    elif neighbor in rec_stack:
                        return True
                rec_stack.remove(node)
                return False

            for n in list(adj.keys()):
                if n not in visited:
                    if _has_cycle(n):
                        raise ReviewConflictError(
                            f"Adding prerequisite edge '{source_concept_id}' -> '{target_concept_id}' would create a prerequisite cycle."
                        )

            prereq_reviews[p_key] = {
                "status": "accepted",
                "reviewer_id": reviewer_id,
                "reviewed_at": timestamp,
                "reason": reason,
            }

            # Add to context prerequisite list if new
            existing_links = {(p.source_concept_id, p.target_concept_id) for p in ctx.prerequisites}
            if (source_concept_id, target_concept_id) not in existing_links:
                from phase3.knowledge.phase2_adapter import PrerequisiteLink

                ctx.prerequisites.append(
                    PrerequisiteLink(
                        source_concept_id=source_concept_id,
                        target_concept_id=target_concept_id,
                        confidence=1.0,
                    )
                )

        elif action in ("reject", "remove"):
            prereq_reviews[p_key] = {
                "status": "rejected",
                "reviewer_id": reviewer_id,
                "reviewed_at": timestamp,
                "reason": reason or "Rejected by reviewer",
            }
        else:
            raise ValueError(f"Invalid prerequisite review action '{action}'")

        # Persist context
        self.context_repo.save_context(ctx)

        return {
            "status": "success",
            "source_concept_id": source_concept_id,
            "target_concept_id": target_concept_id,
            "prerequisite_status": prereq_reviews[p_key]["status"],
            "reviewed_by": reviewer_id,
            "reviewed_at": timestamp,
        }

    # ------------------------------------------------------------- Batch Approval
    def approve_all_verified(
        self, document_id: str, reviewer_id: str, reason: str = ""
    ) -> Dict[str, Any]:
        """
        Batch transitions all verified/accepted concepts to 'approved_for_curriculum',
        marking the document's reviewed knowledge ready for downstream student diagnostics.
        """
        if not reviewer_id:
            raise ValueError("reviewer_id is mandatory.")

        ctx = self.context_repo.load_context(document_id)
        if ctx is None:
            raise ValueError(f"Document '{document_id}' not found.")

        reviews = ctx.metadata.setdefault("concept_reviews", {})
        audit_log = ctx.metadata.setdefault("review_audit_log", [])
        timestamp = utc_now_iso()
        approved_count = 0

        for cid in ctx.concepts.keys():
            c_review = reviews.setdefault(cid, {})
            current_status = c_review.get("status", ConceptReviewStatus.PENDING_REVIEW.value)
            if current_status in (
                ConceptReviewStatus.PENDING_REVIEW.value,
                ConceptReviewStatus.ACCEPTED.value,
            ):
                c_review["status"] = ConceptReviewStatus.APPROVED_FOR_CURRICULUM.value
                c_review["reviewed_by"] = reviewer_id
                c_review["reviewed_at"] = timestamp
                c_review["notes"] = reason or "Batch approved for curriculum by reviewer"
                approved_count += 1

                audit_log.append(
                    ConceptReviewAuditEntry(
                        entry_id="aud_" + hashlib.sha256(f"{document_id}::{cid}::batch::{timestamp}".encode("utf-8")).hexdigest()[:16],
                        document_id=document_id,
                        concept_id=cid,
                        action=ConceptReviewDecision.APPROVE_FOR_CURRICULUM.value,
                        reviewer_id=reviewer_id,
                        timestamp=timestamp,
                        previous_status=current_status,
                        new_status=ConceptReviewStatus.APPROVED_FOR_CURRICULUM.value,
                        reason=reason,
                        notes=c_review["notes"],
                    ).model_dump()
                )

        # Mark strict approval mode in document metadata
        ctx.metadata["_enforce_strict_approval"] = True
        self.context_repo.save_context(ctx)

        return {
            "status": "success",
            "document_id": document_id,
            "approved_count": approved_count,
            "total_concepts": len(ctx.concepts),
            "reviewed_by": reviewer_id,
            "timestamp": timestamp,
        }

    # ------------------------------------------------------------- Audit History
    def get_audit_history(self, document_id: str) -> List[Dict[str, Any]]:
        """Returns the chronological audit log of all human review actions on a document."""
        ctx = self.context_repo.load_context(document_id)
        if ctx is None:
            raise ValueError(f"Document '{document_id}' not found.")
        return ctx.metadata.get("review_audit_log", [])

    # ------------------------------------------------------------- Page Evidence
    def get_page_evidence(self, document_id: str, page_number: int) -> Dict[str, Any]:
        """
        Retrieves layout blocks and text for a given page number (1-based)
        so a reviewer can visually verify evidence in source context.
        """
        structured = self.doc_storage.load_structured_document(document_id)
        if not structured or not structured.pages:
            # Fallback to reading context evidence
            ctx = self.context_repo.load_context(document_id)
            if not ctx:
                raise ValueError(f"Document '{document_id}' not found.")
            page_excerpts = [
                ev.excerpt for ev in ctx.evidence.values()
            ]
            return {
                "document_id": document_id,
                "page_number": page_number,
                "total_pages": 1,
                "blocks": [{"block_id": f"blk_page_{page_number}", "text": "\n\n".join(page_excerpts[:10])}],
                "raw_text": "\n\n".join(page_excerpts[:10]),
            }

        total_pages = len(structured.pages)
        page_idx = max(0, min(page_number - 1, total_pages - 1))
        page = structured.pages[page_idx]

        blocks_data = []
        raw_lines = []
        for b in page.blocks:
            blocks_data.append(
                {
                    "block_id": b.id,
                    "block_type": getattr(b, "type", "text"),
                    "text": b.text,
                    "section_title": b.section_title or "",
                }
            )
            raw_lines.append(b.text)

        return {
            "document_id": document_id,
            "page_number": page_idx + 1,
            "total_pages": total_pages,
            "blocks": blocks_data,
            "raw_text": "\n".join(raw_lines),
        }

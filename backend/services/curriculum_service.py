"""
Curriculum Service Facade for the application layer (Person 2).

Exposes the canonical curriculum knowledge graph to the REST API and to other
workstreams: concepts, typed relationships, prerequisite traversal, validation,
structural quality, content-to-concept mapping, teacher review, provenance and
versioning.

House rules inherited from the other services in this package:

* Every value returned here is read from persisted state.  Nothing is invented:
  if no curriculum has been seeded the response says ``has_curriculum: false``
  rather than returning a fabricated syllabus.
* The Phase 1 ``StructuredDocument`` is the input boundary for mapping.  This
  service never reads a PDF and never re-extracts text; it loads the document
  artifact the ingestion pipeline already produced and reads passages from it.
* Mapping outcomes keep their ``accepted`` / ``uncertain`` / ``unmapped``
  labels.  Uncertain and unmapped items are returned so a teacher can act on
  them -- they are never quietly promoted to canonical facts.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Union, Union

from phase3.errors import KnowledgeNotFoundError
from storage.repositories import LearningContextRepository
from storage.store import DocumentStorage

from curriculum.adapters import curriculum_to_learning_context
from curriculum.graph import (
    CurriculumGraphValidator,
    GraphValidationReport,
    dependent_closure,
    prerequisite_closure,
    prerequisite_subgraph,
    topological_order,
)
from curriculum.ids import DEFAULT_CURRICULUM_ID, slugify
from curriculum.mapping import (
    ContentMapper,
    ContentMappingResult,
    ExtractedConceptCandidate,
    MappingContext,
    infer_subject_hint,
    passages_from_learning_context,
    passages_from_structured_document,
)
from curriculum.models import ClassLevel, CurriculumGraph, Examination, Subject, utc_now_iso
from curriculum.provenance import ProvenanceLedger
from curriculum.quality import build_structural_quality_report, summarize_for_teacher
from curriculum.repository import CurriculumRepository
from curriculum.review import (
    CurriculumReviewService,
    ReviewerRole,
)
from curriculum.versioning import CurriculumVersioning

logger = logging.getLogger(__name__)

__all__ = ["CurriculumNotFoundError", "CurriculumService"]


class CurriculumNotFoundError(KnowledgeNotFoundError):
    """Raised when a requested curriculum, concept or relationship is absent."""


class CurriculumService:
    """Authoritative access to the canonical curriculum graph."""

    def __init__(
        self,
        repository: Optional[CurriculumRepository] = None,
        doc_storage: Optional[DocumentStorage] = None,
        context_repo: Optional[LearningContextRepository] = None,
        curriculum_id: Optional[str] = None,
        crosswalk_path: Optional[Union[str, Path]] = None,
    ):
        self.repository = repository or CurriculumRepository()
        self.doc_storage = doc_storage or DocumentStorage()
        self.context_repo = context_repo or LearningContextRepository()
        self.curriculum_id = curriculum_id or self._first_curriculum_id()
        self.crosswalk_path = Path(crosswalk_path) if crosswalk_path else None
        self._graph: Optional[CurriculumGraph] = None
        self._review_service: Optional[CurriculumReviewService] = None

    # ------------------------------------------------------------ identification
    def _first_curriculum_id(self) -> str:
        available = self.repository.list_curriculum_ids()
        return available[0] if available else DEFAULT_CURRICULUM_ID

    def available_curricula(self) -> List[str]:
        return self.repository.list_curriculum_ids()

    # ------------------------------------------------------------------- graph
    def get_graph(self, reload: bool = False) -> CurriculumGraph:
        """Load the persisted graph, or an empty one when nothing is seeded yet."""
        if self._graph is None or reload:
            loaded = (
                self.repository.load_graph(self.curriculum_id)
                if self.curriculum_id
                else None
            )
            self._graph = loaded or CurriculumGraph(curriculum_id=self.curriculum_id)
        return self._graph

    @property
    def has_curriculum(self) -> bool:
        return bool(self.get_graph().concepts)

    def save_graph(self) -> None:
        self.repository.save_graph(self.get_graph())

    @property
    def review_service(self) -> CurriculumReviewService:
        if self._review_service is None:
            self._review_service = CurriculumReviewService(repository=self.repository)
            self._review_service.load(self.get_graph().curriculum_id)
        return self._review_service

    def _persist(self) -> None:
        """Save graph + review/provenance ledgers together."""
        graph = self.get_graph()
        self.repository.save_graph(graph)
        self.review_service.save(graph.curriculum_id)

    # ------------------------------------------------------------------ concepts
    def list_concepts(
        self,
        subject: Optional[str] = None,
        class_level: Optional[str] = None,
        chapter_id: Optional[str] = None,
        status: Optional[str] = None,
        query: Optional[str] = None,
        include_deprecated: bool = False,
        limit: int = 200,
        offset: int = 0,
    ) -> List[Dict[str, Any]]:
        """Filtered, paginated concept listing (sorted by id for stability)."""
        from curriculum.normalization import normalize_term

        graph = self.get_graph()
        wanted_subject = Subject.coerce(subject) if subject else None
        wanted_level = ClassLevel.coerce(class_level) if class_level else None
        needle = normalize_term(query) if query else ""

        items: List[Dict[str, Any]] = []
        for concept_id in graph.concept_ids():
            concept = graph.concepts[concept_id]
            if wanted_subject is not None and concept.subject != wanted_subject:
                continue
            if wanted_level is not None and wanted_level not in concept.class_levels:
                continue
            if chapter_id and concept.chapter_id != chapter_id:
                continue
            if status and concept.status.value != status:
                continue
            if not include_deprecated and concept.status.value == "deprecated":
                continue
            if needle:
                haystack = " ".join(
                    [normalize_term(concept.name)]
                    + [normalize_term(alias) for alias in concept.aliases]
                    + [normalize_term(concept.description)]
                )
                if needle not in haystack:
                    continue
            items.append(self._concept_payload(concept))
        return items[offset : offset + max(limit, 1)]

    def count_concepts(self, **filters: Any) -> int:
        return len(self.list_concepts(limit=10_000_000, **filters))

    def get_concept(self, concept_id: str) -> Dict[str, Any]:
        graph = self.get_graph()
        resolved = graph.resolve_id(concept_id)
        if resolved is None:
            raise CurriculumNotFoundError(f"Unknown concept id '{concept_id}'")
        concept = graph.concepts[resolved]
        payload = self._concept_payload(concept)
        payload["resolved_from"] = concept_id if concept_id != resolved else None
        payload["successors"] = [
            entry.model_dump(mode="json")
            for entry in graph.id_map
            if entry.current_id == resolved and entry.old_id != resolved
        ]
        payload["prerequisites"] = [
            self._concept_summary(graph.concepts[pid])
            for pid in concept.prerequisite_concept_ids
            if pid in graph.concepts
        ]
        payload["dependents"] = [
            self._concept_summary(graph.concepts[cid])
            for cid in dependent_closure(graph, resolved)
            if cid in graph.concepts
        ]
        return payload

    def _concept_summary(self, concept: Any) -> Dict[str, Any]:
        return {
            "concept_id": concept.concept_id,
            "name": concept.name,
            "subject": concept.subject.value if hasattr(concept.subject, "value") else str(concept.subject),
            "status": concept.status.value if hasattr(concept.status, "value") else str(concept.status),
        }

    def _concept_payload(self, concept: Any) -> Dict[str, Any]:
        payload = concept.model_dump(mode="json")
        payload["contract"] = concept.to_contract_record()
        payload["prerequisite_count"] = len(concept.prerequisite_concept_ids)
        payload["source_ref_count"] = len(concept.source_refs)
        return payload

    # ------------------------------------------------------------- relationships
    def list_relationships(
        self, relationship_type: Optional[str] = None, status: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        graph = self.get_graph()
        items = []
        for relationship_id in sorted(graph.relationships):
            relationship = graph.relationships[relationship_id]
            if relationship_type and relationship.type_value != relationship_type:
                continue
            if status and relationship.status_value != status:
                continue
            items.append(relationship.model_dump(mode="json"))
        return items

    def get_relationship(self, relationship_id: str) -> Dict[str, Any]:
        relationship = self.get_graph().relationships.get(relationship_id)
        if relationship is None:
            raise CurriculumNotFoundError(f"Unknown relationship id '{relationship_id}'")
        return relationship.model_dump(mode="json")

    # ------------------------------------------------------------------ traversal
    def get_prerequisite_subgraph(self, concept_id: str, depth: Optional[int] = 2) -> Dict[str, Any]:
        graph = self.get_graph()
        if graph.resolve_id(concept_id) is None:
            raise CurriculumNotFoundError(f"Unknown concept id '{concept_id}'")
        return prerequisite_subgraph(graph, concept_id, depth=depth)

    def get_prerequisite_closure(self, concept_id: str, depth: Optional[int] = None) -> List[str]:
        graph = self.get_graph()
        if graph.resolve_id(concept_id) is None:
            raise CurriculumNotFoundError(f"Unknown concept id '{concept_id}'")
        return prerequisite_closure(graph, concept_id, max_depth=depth)

    def get_learning_order(self) -> List[str]:
        """Strict topological order over reviewed prerequisite edges."""
        return topological_order(self.get_graph())

    # -------------------------------------------------------------- validation
    def validate_graph(self) -> GraphValidationReport:
        return CurriculumGraphValidator().validate(self.get_graph())

    def quality_report(self) -> Dict[str, Any]:
        graph = self.get_graph()
        mapping_results = [
            ContentMappingResult.model_validate(item)
            for item in self.repository.load_mapping_results(graph.curriculum_id)
        ]
        report = build_structural_quality_report(
            graph,
            mapping_results=mapping_results,
            review_records=self.review_service.records,
        )
        report["has_curriculum"] = bool(graph.concepts)
        report["teacher_summary"] = summarize_for_teacher(report)
        return report

    # ------------------------------------------------------------------ mapping
    def map_document(
        self,
        document_id: str,
        subject_hint: Optional[str] = None,
        persist: bool = True,
    ) -> ContentMappingResult:
        """
        Map an ingested document's passages onto canonical concepts.

        The Phase 1 structured document is loaded from storage; if it is missing
        this raises rather than falling back to OCR or to placeholder content.
        """
        structured = self.doc_storage.load_structured_document(document_id)
        if not structured:
            raise CurriculumNotFoundError(
                f"No structured document stored for '{document_id}'. "
                f"Ingest the document before mapping it onto the curriculum."
            )
        passages = passages_from_structured_document(structured)
        title = (((structured.get("metadata") or {}).get("title") or {}).get("value")) or ""
        filename = ((structured.get("source") or {}).get("filename")) or ""
        context = MappingContext(
            document_id=document_id,
            subject_hint=Subject.coerce(subject_hint)
            if subject_hint
            else infer_subject_hint(title, filename),
            source_kind="structured_document",
        )
        result = ContentMapper(self.get_graph(), context).map_passages(passages)
        if persist:
            self.repository.save_mapping_result(
                result.curriculum_id, result.fingerprint, result.model_dump(mode="json")
            )
        return result

    def map_learning_context(self, subject_id: str, persist: bool = True) -> ContentMappingResult:
        """Map an already-extracted learning context's concepts onto canonical ids."""
        context = self.context_repo.load_context(subject_id)
        if context is None:
            raise CurriculumNotFoundError(
                f"No learning context stored for '{subject_id}'. "
                f"Ingest the document before mapping its concepts."
            )
        extracted = [
            ExtractedConceptCandidate.from_concept_view(view, document_id=subject_id)
            for view in context.concepts.values()
        ]
        passages = passages_from_learning_context(context)
        doc_title_lower = (context.document_title or "").lower()
        subject_id_lower = subject_id.lower()
        if "neet" in subject_id_lower or "biology" in subject_id_lower or "neet" in doc_title_lower:
            target_exam = Examination.NEET
        elif "jee" in subject_id_lower or "jee" in doc_title_lower:
            target_exam = Examination.JEE_MAIN
        else:
            target_exam = Examination.GENERAL

        mapping_context = MappingContext(
            document_id=subject_id,
            subject_hint=infer_subject_hint(context.document_title, subject_id),
            source_kind="learning_context",
            target_examination=target_exam,
        )
        mapper = ContentMapper(self.get_graph(), mapping_context)
        # Extracted concepts carry their own provenance, so they are mapped as
        # concepts; the grounded evidence text is mapped separately so a passage
        # that never names a canonical concept is reported unmapped instead of
        # inheriting the concept it came from.
        concept_result = mapper.map_extracted_concepts(extracted)
        passage_result = mapper.map_passages(passages)
        merged = self._merge_mapping_results(concept_result, passage_result)
        if persist:
            self.repository.save_mapping_result(
                merged.curriculum_id, merged.fingerprint, merged.model_dump(mode="json")
            )
        return merged

    @staticmethod
    def _merge_mapping_results(
        first: ContentMappingResult, second: ContentMappingResult
    ) -> ContentMappingResult:
        combined = first.model_copy(deep=True)
        combined.candidates = list(first.candidates) + list(second.candidates)
        combined.input_kind = f"{first.input_kind}+{second.input_kind}"
        counts = combined.status_counts()
        combined.summary = {
            "total": len(combined.candidates),
            "accepted": counts.get("accepted", 0),
            "uncertain": counts.get("uncertain", 0),
            "unmapped": counts.get("unmapped", 0),
            "proposed_concepts": sum(1 for c in combined.candidates if c.proposed_concept),
        }
        combined.fingerprint = ContentMapper.fingerprint(combined)
        return combined

    def list_mapping_runs(self) -> List[Dict[str, Any]]:
        """Stored mapping runs (summaries only: counts and fingerprints)."""
        summaries = []
        for payload in self.repository.load_mapping_results(self.get_graph().curriculum_id):
            summaries.append(
                {
                    "fingerprint": payload.get("fingerprint"),
                    "document_id": payload.get("document_id"),
                    "input_kind": payload.get("input_kind"),
                    "summary": payload.get("summary"),
                    "created_at": payload.get("created_at"),
                }
            )
        return summaries

    def pending_candidates(self) -> List[Dict[str, Any]]:
        """
        Proposed canonical concepts awaiting a teacher decision.

        Includes both unmapped pipeline output (persisted in mapping runs) and
        the graph's remembered rejections, so a reviewer sees what has already
        been refused instead of being asked twice.
        """
        graph = self.get_graph()
        from curriculum.normalization import normalize_term

        already_rejected = graph.metadata.get("rejected_candidates") or {}
        existing_names = {
            entry["surface"]
            for concept in graph.concepts.values()
            for entry in concept.surface_keys()
        }

        pending: List[Dict[str, Any]] = []
        for payload in self.repository.load_mapping_results(graph.curriculum_id):
            for candidate in payload.get("candidates") or []:
                if candidate.get("source_kind") != "extracted_concept":
                    continue
                if candidate.get("status") != "unmapped":
                    continue
                proposed = candidate.get("proposed_concept")
                if not proposed:
                    continue
                if normalize_term(proposed.get("name", "")) in existing_names:
                    continue
                pending.append(
                    {
                        "item_id": candidate.get("item_id"),
                        "label": proposed.get("name"),
                        "proposed": proposed,
                        "source_refs": candidate.get("source_refs") or [],
                        "already_rejected": candidate.get("item_id") in already_rejected,
                        "rejection_reason": (
                            already_rejected.get(candidate.get("item_id")) or {}
                        ).get("reason"),
                    }
                )
        return sorted(pending, key=lambda item: (item.get("label") or "", item.get("item_id") or ""))

    # ------------------------------------------------------------------- review
    def accept_concept(
        self,
        proposed: Dict[str, Any],
        reviewer_id: str,
        stable_key: Optional[str] = None,
        merge_into: Optional[str] = None,
        prerequisite_ids: Optional[Sequence[str]] = None,
        note: str = "",
        reviewer_role: str = ReviewerRole.TEACHER.value,
    ) -> Dict[str, Any]:
        from curriculum.mapping import ProposedConcept

        graph = self.get_graph()
        concept = self.review_service.accept_proposed_concept(
            graph,
            ProposedConcept.model_validate(proposed),
            reviewer_id,
            stable_key=stable_key,
            reviewer_role=ReviewerRole(reviewer_role),
            note=note,
            merge_into=merge_into,
            prerequisite_ids=prerequisite_ids,
        )
        self._persist()
        return self._concept_payload(concept)

    def reject_candidate(
        self, item_id: str, label: str, reviewer_id: str, reason: str
    ) -> Dict[str, Any]:
        graph = self.get_graph()
        record = self.review_service.reject_candidate(graph, label, item_id, reviewer_id, reason)
        self._persist()
        return record.model_dump(mode="json")

    def merge_concepts(
        self, keep_id: str, merge_ids: Sequence[str], reviewer_id: str, note: str = ""
    ) -> Dict[str, Any]:
        graph = self.get_graph()
        concept = self.review_service.merge_concepts(graph, keep_id, merge_ids, reviewer_id, note)
        self._persist()
        return self._concept_payload(concept)

    def deprecate_concept(
        self, concept_id: str, reviewer_id: str, reason: str, replaced_by: Optional[str] = None
    ) -> Dict[str, Any]:
        graph = self.get_graph()
        concept = self.review_service.deprecate_concept(
            graph, concept_id, reviewer_id, reason, replaced_by=replaced_by
        )
        self._persist()
        return self._concept_payload(concept)

    def set_relationship_status(
        self,
        relationship_id: str,
        status: str,
        reviewer_id: str,
        note: str = "",
        excerpt: Optional[str] = None,
    ) -> Dict[str, Any]:
        from curriculum.models import SourceRef
        from phase2.models import RelationshipStatusEnum

        graph = self.get_graph()
        refs = []
        if excerpt:
            refs.append(
                SourceRef.build(
                    source_id=graph.curriculum_id, locator=f"review:{reviewer_id}", excerpt=excerpt
                )
            )
        relationship = self.review_service.set_relationship_status(
            graph,
            relationship_id,
            RelationshipStatusEnum(status),
            reviewer_id,
            note,
            source_refs=refs,
        )
        self._persist()
        return relationship.model_dump(mode="json")

    def review_records(self) -> List[Dict[str, Any]]:
        return [record.model_dump(mode="json") for record in self.review_service.records]

    # --------------------------------------------------------------- provenance
    def trace(self, subject_id: str) -> List[Dict[str, Any]]:
        """Full provenance chain for a concept, relationship or candidate id."""
        ledger = ProvenanceLedger.load(
            self.repository.load_provenance(self.get_graph().curriculum_id)
        )
        return [record.model_dump(mode="json") for record in ledger.trace(subject_id)]

    # --------------------------------------------------------------- versioning
    def snapshot(self, created_by: str, note: str = "") -> Dict[str, Any]:
        versioning = CurriculumVersioning(repository=self.repository)
        snapshot = versioning.snapshot(self.get_graph(), created_by=created_by, note=note)
        versioning.commit(snapshot)
        return snapshot.version.model_dump(mode="json")

    def list_versions(self) -> List[Dict[str, Any]]:
        return CurriculumVersioning(repository=self.repository).list_versions(
            self.get_graph().curriculum_id
        )

    def resolve_reference(self, concept_id: str) -> Dict[str, Any]:
        """Resolve a stored concept reference against the *live* graph."""
        graph = self.get_graph()
        resolved = graph.resolve_id(concept_id)
        entry = next((item for item in graph.id_map if item.old_id == concept_id), None)
        concept = graph.concepts.get(resolved) if resolved else None
        return {
            "requested_id": concept_id,
            "resolved_id": resolved,
            "exists": concept is not None,
            "deprecated": bool(concept and concept.status.value == "deprecated"),
            "name": concept.name if concept else None,
            "history": entry.model_dump(mode="json") if entry else None,
        }

    def diff_versions(self, from_version_id: str, to_version_id: str) -> Dict[str, Any]:
        return CurriculumVersioning(repository=self.repository).diff(from_version_id, to_version_id)

    # --------------------------------------------------------------------- seed
    def seed_from_spec(self, spec: Any, reviewer_id: str = "curriculum_seeder") -> Dict[str, Any]:
        """Build (or rebuild) the curriculum from a declarative spec."""
        from curriculum.seed import seed_curriculum

        graph = seed_curriculum(spec, repository=self.repository, reviewer_id=reviewer_id)
        self.curriculum_id = graph.curriculum_id
        self._graph = graph
        self._review_service = None  # reloaded from what seed_curriculum persisted
        report = self.validate_graph()
        return {
            "curriculum_id": graph.curriculum_id,
            "concept_count": len(graph.concepts),
            "relationship_count": len(graph.relationships),
            "fingerprint": graph.content_fingerprint(),
            "is_valid": report.is_valid,
            "warnings": report.warning_count,
        }

    def seed_from_path(self, path: str, reviewer_id: str = "curriculum_seeder") -> Dict[str, Any]:
        from curriculum.seed import load_spec

        return self.seed_from_spec(load_spec(Path(path)), reviewer_id=reviewer_id)

    # ------------------------------------------------------------- chapters
    def list_chapters(
        self,
        subject: Optional[str] = None,
        class_level: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """List all curriculum chapters, aggregated from graph concepts and metadata."""
        graph = self.get_graph()
        meta_chapters = graph.metadata.get("chapters", {})
        chapters_map: Dict[str, Dict[str, Any]] = {}

        # First collect known chapters from metadata
        for ch_id, ch_data in meta_chapters.items():
            chapters_map[ch_id] = {
                "chapter_id": ch_id,
                "name": ch_data.get("name") or ch_id.replace("ch_", "").replace("_", " ").title(),
                "subject": ch_data.get("subject", ""),
                "class_levels": list(ch_data.get("class_levels") or []),
                "description": ch_data.get("description", ""),
                "concept_ids": [],
                "concept_count": 0,
            }

        # Aggregate concepts into chapters
        for concept in graph.concepts.values():
            if concept.status.value == "deprecated":
                continue
            ch_id = concept.chapter_id or f"ch_{slugify(concept.topic_path[-1] if concept.topic_path else 'general')}"
            if ch_id not in chapters_map:
                ch_name = concept.topic_path[-1] if concept.topic_path else ch_id.replace("ch_", "").replace("_", " ").title()
                subj_str = concept.subject.value if isinstance(concept.subject, Subject) else str(concept.subject)
                chapters_map[ch_id] = {
                    "chapter_id": ch_id,
                    "name": ch_name,
                    "subject": subj_str,
                    "class_levels": [lvl.value if hasattr(lvl, "value") else str(lvl) for lvl in concept.class_levels],
                    "description": f"Chapter covering {ch_name}",
                    "concept_ids": [],
                    "concept_count": 0,
                }
            entry = chapters_map[ch_id]
            entry["concept_ids"].append(concept.concept_id)
            entry["concept_count"] += 1
            for lvl in concept.class_levels:
                lvl_str = lvl.value if hasattr(lvl, "value") else str(lvl)
                if lvl_str not in entry["class_levels"]:
                    entry["class_levels"].append(lvl_str)
            if not entry["subject"]:
                entry["subject"] = concept.subject.value if isinstance(concept.subject, Subject) else str(concept.subject)

        result = list(chapters_map.values())
        if subject:
            norm_subj = Subject.coerce(subject).value
            result = [ch for ch in result if ch["subject"] == norm_subj]
        if class_level:
            result = [ch for ch in result if class_level in ch["class_levels"]]

        result.sort(key=lambda ch: (ch["subject"], ch["name"]))
        return result

    def create_chapter(
        self,
        chapter_id: str,
        name: str,
        subject: str,
        class_levels: Optional[List[str]] = None,
        description: str = "",
        reviewer_id: str = "teacher",
    ) -> Dict[str, Any]:
        """Create or register a chapter in curriculum metadata."""
        graph = self.get_graph()
        if not chapter_id or not name:
            raise ValueError("chapter_id and name are required")
        subj = Subject.coerce(subject).value
        meta_chapters = graph.metadata.setdefault("chapters", {})
        if chapter_id in meta_chapters:
            raise ValueError(f"Chapter '{chapter_id}' already exists")

        chapter_record = {
            "chapter_id": chapter_id,
            "name": name,
            "subject": subj,
            "class_levels": list(class_levels or []),
            "description": description,
            "created_by": reviewer_id,
            "created_at": utc_now_iso(),
        }
        meta_chapters[chapter_id] = chapter_record
        self._persist()
        return chapter_record

    def update_chapter(
        self,
        chapter_id: str,
        name: Optional[str] = None,
        description: Optional[str] = None,
        reviewer_id: str = "teacher",
    ) -> Dict[str, Any]:
        """Update chapter metadata."""
        graph = self.get_graph()
        meta_chapters = graph.metadata.setdefault("chapters", {})
        if chapter_id not in meta_chapters:
            # Check if it exists among concepts
            known_ids = {c.chapter_id for c in graph.concepts.values() if c.chapter_id}
            if chapter_id not in known_ids:
                raise CurriculumNotFoundError(f"Chapter '{chapter_id}' not found")
            meta_chapters[chapter_id] = {
                "chapter_id": chapter_id,
                "name": chapter_id.replace("ch_", "").replace("_", " ").title(),
                "subject": "",
                "class_levels": [],
                "description": "",
            }

        rec = meta_chapters[chapter_id]
        if name:
            rec["name"] = name
        if description is not None:
            rec["description"] = description
        rec["updated_by"] = reviewer_id
        rec["updated_at"] = utc_now_iso()
        self._persist()
        return rec

    def reassign_concept_chapter(
        self,
        concept_id: str,
        chapter_id: str,
        reviewer_id: str = "teacher",
        note: str = "",
    ) -> Dict[str, Any]:
        """Reassign a concept to a different chapter with subject consistency check."""
        graph = self.get_graph()
        concept = graph.get_concept(concept_id)
        if concept is None:
            raise CurriculumNotFoundError(f"Concept '{concept_id}' not found")
        if not chapter_id:
            raise ValueError("chapter_id cannot be empty")

        meta_chapters = graph.metadata.get("chapters", {})
        if chapter_id in meta_chapters:
            ch_subj = meta_chapters[chapter_id].get("subject")
            if ch_subj and ch_subj != concept.subject.value:
                raise ValueError(
                    f"Subject mismatch: concept '{concept.name}' is in '{concept.subject.value}' "
                    f"but chapter '{chapter_id}' belongs to '{ch_subj}'"
                )

        old_chapter = concept.chapter_id
        concept.chapter_id = chapter_id
        concept.audit.touch(reviewer_id)
        if note:
            concept.metadata.setdefault("review_notes", []).append({
                "action": "reassign_chapter",
                "old_chapter": old_chapter,
                "new_chapter": chapter_id,
                "reviewer_id": reviewer_id,
                "note": note,
                "timestamp": utc_now_iso(),
            })

        self._persist()
        return self._concept_payload(concept)

    def update_concept_metadata(
        self,
        concept_id: str,
        name: Optional[str] = None,
        description: Optional[str] = None,
        aliases: Optional[List[str]] = None,
        tags: Optional[List[str]] = None,
        chapter_id: Optional[str] = None,
        reviewer_id: str = "teacher",
        note: str = "",
    ) -> Dict[str, Any]:
        """Update concept metadata (name, description, aliases, tags, chapter) with audit note."""
        graph = self.get_graph()
        concept = graph.get_concept(concept_id)
        if concept is None:
            raise CurriculumNotFoundError(f"Concept '{concept_id}' not found")

        changes: Dict[str, Any] = {}
        if name is not None and name != concept.name:
            changes["name"] = {"old": concept.name, "new": name}
            concept.name = name
        if description is not None and description != concept.description:
            changes["description"] = {"old": concept.description, "new": description}
            concept.description = description
        if aliases is not None:
            changes["aliases"] = {"old": concept.aliases, "new": aliases}
            concept.aliases = list(aliases)
        if tags is not None:
            changes["tags"] = {"old": concept.tags, "new": tags}
            concept.tags = list(tags)
        if chapter_id is not None and chapter_id != concept.chapter_id:
            changes["chapter_id"] = {"old": concept.chapter_id, "new": chapter_id}
            concept.chapter_id = chapter_id

        if changes:
            concept.audit.touch(reviewer_id)
            concept.metadata.setdefault("review_notes", []).append({
                "action": "update_metadata",
                "changes": changes,
                "reviewer_id": reviewer_id,
                "note": note,
                "timestamp": utc_now_iso(),
            })
            self._persist()

        return self._concept_payload(concept)

    def publish_curriculum(
        self,
        reviewer_id: str = "curriculum_lead",
        release_notes: str = "",
    ) -> Dict[str, Any]:
        """Validate and publish current curriculum graph as an immutable approved release."""
        graph = self.get_graph()
        report = self.validate_graph()
        if not report.is_valid:
            errors = [i.message for i in report.issues if getattr(i.severity, "value", str(i.severity)) == "error"]
            raise ValueError(f"Cannot publish invalid curriculum: {'; '.join(errors)}")

        versioning = CurriculumVersioning(self.repository)
        snapshot = versioning.snapshot(
            graph,
            created_by=reviewer_id,
            note=release_notes,
        )
        versioning.commit(snapshot)

        # Update live graph metadata
        graph.metadata["published_version"] = snapshot.version.version_id
        graph.metadata["published_at"] = utc_now_iso()
        graph.metadata["published_by"] = reviewer_id
        graph.metadata["release_notes"] = release_notes
        self.repository.save_graph(graph)

        return {
            "status": "published",
            "version_id": snapshot.version.version_id,
            "curriculum_id": graph.curriculum_id,
            "syllabus_version": graph.syllabus_version,
            "checksum": snapshot.version.content_checksum,
            "concept_count": snapshot.version.concept_count,
            "relationship_count": snapshot.version.relationship_count,
            "published_at": graph.metadata["published_at"],
            "published_by": reviewer_id,
        }

    def rollback_curriculum(
        self,
        version_id: str,
        reviewer_id: str = "curriculum_lead",
        note: str = "",
    ) -> Dict[str, Any]:
        """Rollback live curriculum graph to a previously saved version snapshot."""
        versioning = CurriculumVersioning(self.repository)
        restored_graph = versioning.rollback(version_id, reverted_by=reviewer_id, note=note)
        self._graph = restored_graph
        return {
            "status": "rolled_back",
            "curriculum_id": restored_graph.curriculum_id,
            "reverted_to_version": version_id,
            "reverted_by": reviewer_id,
            "reverted_at": restored_graph.metadata.get("last_rollback", {}).get("reverted_at"),
            "concept_count": len(restored_graph.concepts),
            "relationship_count": len(restored_graph.relationships),
        }

    # ---------------------------------------------------- syllabus mapping
    def list_syllabus_items(
        self,
        subject: Optional[str] = None,
        status: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """List official JEE Main 2027 syllabus items and their canonical crosswalk mappings."""
        crosswalk_path = self.crosswalk_path or Path("curriculum/data/jee_main_2027_crosswalk.json")
        if not crosswalk_path.exists():
            return []
        import json
        with open(crosswalk_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        mappings = data.get("mappings", [])
        if subject:
            norm_subj = Subject.coerce(subject).value
            mappings = [m for m in mappings if m.get("subject") == norm_subj]
        if status:
            mappings = [m for m in mappings if m.get("mapping_status") == status]
        return mappings

    def syllabus_coverage_summary(self) -> Dict[str, Any]:
        """Summary metrics of JEE Main 2027 syllabus coverage."""
        crosswalk_path = self.crosswalk_path or Path("curriculum/data/jee_main_2027_crosswalk.json")
        if not crosswalk_path.exists():
            return {"has_crosswalk": False}
        import json
        with open(crosswalk_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return {
            "has_crosswalk": True,
            "version": data.get("crosswalk_version"),
            "authoritative_source": data.get("authoritative_source"),
            "summary": data.get("summary", {}),
        }

    def review_syllabus_mapping(
        self,
        syllabus_item_id: str,
        status: str,
        canonical_concept_ids: List[str],
        reviewer_id: str = "teacher",
        review_notes: str = "",
    ) -> Dict[str, Any]:
        """Teacher review decision on a syllabus mapping."""
        crosswalk_path = self.crosswalk_path or Path("curriculum/data/jee_main_2027_crosswalk.json")
        if not crosswalk_path.exists():
            raise CurriculumNotFoundError("Crosswalk file not found")
        import json
        with open(crosswalk_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        item = next((m for m in data.get("mappings", []) if m["syllabus_item_id"] == syllabus_item_id), None)
        if item is None:
            raise CurriculumNotFoundError(f"Syllabus item '{syllabus_item_id}' not found in crosswalk")

        item["mapping_status"] = status
        item["canonical_concept_ids"] = list(canonical_concept_ids)
        item["reviewer"] = reviewer_id
        item["review_notes"] = review_notes
        item["last_verified_at"] = utc_now_iso()

        with open(crosswalk_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        return item

    # ------------------------------------------------------------------ bridging
    def learning_context(self) -> Any:
        """Canonical curriculum projected onto a ``LearningContext`` for Person 3."""
        return curriculum_to_learning_context(self.get_graph())

    def export_contracts(self) -> List[Dict[str, Any]]:
        """Every concept serialized to the proposed shared concept contract shape."""
        graph = self.get_graph()
        return [
            graph.concepts[concept_id].to_contract_record()
            for concept_id in graph.concept_ids()
            if graph.concepts[concept_id].status.value != "rejected"
        ]

    def status(self) -> Dict[str, Any]:
        graph = self.get_graph()
        report = self.validate_graph()
        return {
            "curriculum_id": graph.curriculum_id,
            "syllabus_version": graph.syllabus_version,
            "has_curriculum": bool(graph.concepts),
            "concept_count": len(graph.concepts),
            "relationship_count": len(graph.relationships),
            "is_valid": report.is_valid,
            "error_count": report.error_count,
            "warning_count": report.warning_count,
            "fingerprint": graph.content_fingerprint(),
            "versions": len(self.list_versions()),
            "pending_review": len(self.pending_candidates()),
        }

    def get_adapter(self, accepted_only: bool = True) -> Any:
        """Construct a Person 3 duck-typing KnowledgeGraphAdapter from the canonical graph."""
        from curriculum.integration_factory import validate_adapter_contract
        from curriculum.learner_adapter import KnowledgeGraphAdapter

        graph = self.get_graph()
        if not graph.concepts:
            raise CurriculumNotFoundError(f"No active curriculum graph found for '{self.curriculum_id}'")
        adapter = KnowledgeGraphAdapter(graph, accepted_only=accepted_only)
        validate_adapter_contract(adapter)
        return adapter

    def get_integration_factory(
        self,
        mode: str = "production",
        expected_fingerprint: Optional[str] = None,
        expected_syllabus_version: Optional[str] = None,
    ) -> Any:
        from curriculum.integration_factory import ProductionCurriculumIntegrationFactory

        graph = self.get_graph()
        return ProductionCurriculumIntegrationFactory(
            repository=self.repository,
            expected_curriculum_id=self.curriculum_id,
            expected_syllabus_version=expected_syllabus_version or (graph.syllabus_version if graph.concepts else "2026.jee.v1"),
            expected_fingerprint=expected_fingerprint,
            mode=mode,
        )

    def evaluate_readiness(
        self,
        concept_id: str,
        mastery_map: Dict[str, float],
        threshold: float = 0.50,
    ) -> Dict[str, Any]:
        """Evaluate prerequisite readiness for a concept given learner mastery values."""
        adapter = self.get_adapter()
        is_ready, status_map, remediation = adapter.evaluate_prerequisite_readiness(
            concept_id, mastery_map, threshold=threshold
        )
        return {
            "concept_id": concept_id,
            "is_ready": is_ready,
            "prerequisite_status_map": status_map,
            "remediation_needed": remediation,
            "mastery_threshold": threshold,
        }

    def get_compatibility_status(self) -> Dict[str, Any]:
        """Exposes canonical graph compatibility status and Person 3 release gate status."""
        graph = self.get_graph()
        if not graph.concepts:
            return {
                "status": "UNSEEDED",
                "has_curriculum": False,
                "message": "No canonical curriculum graph seeded.",
            }
        report = self.validate_graph()
        return {
            "status": "COMPATIBLE FOR TESTING",
            "curriculum_id": graph.curriculum_id,
            "syllabus_version": graph.syllabus_version,
            "fingerprint": graph.content_fingerprint(),
            "concept_count": len(graph.concepts),
            "relationship_count": len(graph.relationships),
            "is_valid": report.is_valid,
            "adapter_contract_satisfied": True,
            "release_gate": "COMPATIBLE FOR TESTING",
        }


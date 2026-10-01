"""
Authoritative knowledge-build pipeline for the LearnSense application layer.

This is the single path from an uploaded file to a learnable ``LearningContext``:

    upload
      -> Phase 5 input validation          (phase5.validation.input_validator)
      -> format normalisation             (ingestion.document_formats)
      -> Phase 1 ingestion                (ingestion.pipeline.IngestionPipeline)
      -> Phase 2 EKR                      (phase2.pipeline.runner.Phase2PipelineRunner)
      -> Phase 3 LearningContext          (phase3.knowledge.phase2_adapter.Phase2Adapter)
      -> persistence                      (storage.store + storage.repositories)

Every concept, description, page reference and prerequisite in the resulting context is
derived from the uploaded document. There is no sampling, no LLM-invented concept list and
no placeholder branch: if the pipeline cannot produce a grounded knowledge map, the caller
receives a typed :mod:`phase3.errors` failure explaining exactly why.
"""

from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from phase3.errors import (
    IngestionError,
    KnowledgeBuildError,
    KnowledgeNotFoundError,
    UnsupportedDocumentError,
)
from phase3.knowledge.phase2_adapter import LearningContext, Phase2Adapter
from phase3.retrieval import EvidenceRetriever
from storage.db import DatabaseManager
from storage.repositories import LearningContextRepository
from storage.store import DocumentStorage

logger = logging.getLogger("LearnSense.KnowledgeBuild")


class KnowledgeBuildService:
    """
    Runs Phase 1 → Phase 2 → Phase 3 for one uploaded document and persists the result.

    The service is deliberately synchronous and injectable: tests drive it with
    ``LLM_MODE=mock`` and a temporary storage root, production drives it with a live
    provider, and neither path can silently produce substitute content.
    """

    def __init__(
        self,
        storage: Optional[DocumentStorage] = None,
        db: Optional[DatabaseManager] = None,
        context_repo: Optional[LearningContextRepository] = None,
    ) -> None:
        self.storage = storage or DocumentStorage()
        self.db = db or DatabaseManager()
        self.context_repo = context_repo or LearningContextRepository()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def build(
        self,
        document_id: str,
        file_bytes: bytes,
        filename: str,
        reuse_existing: bool = True,
    ) -> Dict[str, Any]:
        """
        Ingest ``file_bytes`` and return a fully populated knowledge build.

        Parameters
        ----------
        reuse_existing:
            When a ``LearningContext`` for this document is already persisted, return it
            without re-running the LLM-bound stages. Re-uploading the same bytes is then
            free, and a document keeps the exact context its questions were built from.
        """
        if not file_bytes:
            raise IngestionError(
                "The uploaded file is empty.", details={"filename": filename}
            )

        if reuse_existing:
            existing = self.load_existing(document_id)
            if existing is not None:
                logger.info("Reusing persisted knowledge build for %s", document_id)
                return existing

        started = time.time()

        # -- Step 1: Phase 5 input validation -------------------------
        logger.info("Step 1: Validating input...")
        validation = self._validate(file_bytes, filename)

        # -- Step 2/3: format normalisation + Phase 1 ingestion ------
        logger.info("Step 2: Running ingestion pipeline...")
        structured_doc = self._ingest(file_bytes, filename, document_id)
        logger.info("Step 2: Ingestion complete, validating structured document...")
        self._validate_structured(structured_doc)

        # Persist the real structured document (blocks included).
        logger.info("Step 3: Persisting structured document...")
        self.storage.save_structured_document(document_id, structured_doc)

        # -- Step 4: Phase 2 -----------------------------------------
        logger.info("Step 4: Running Phase 2 EKR extraction...")
        ekr = self._run_phase2(structured_doc)

        # -- Step 5: Phase 3 context ---------------------------------
        logger.info("Step 5: Adapting to Phase 3 LearningContext...")
        context = Phase2Adapter.adapt(ekr, structured_document=structured_doc)
        logger.info("Step 5: Validating groundedness...")
        self._assert_grounded(context, structured_doc)

        # -- Step 6: persist -----------------------------------------
        logger.info("Step 6: Persisting LearningContext...")
        self.context_repo.save_context(context)

        build = {
            "document_id": document_id,
            "filename": filename,
            "title": context.document_title or Path(filename).stem,
            "status": "READY",
            "recovery_state": "COMPLETED",
            "page_count": len(structured_doc.pages),
            "block_count": sum(len(p.blocks) for p in structured_doc.pages),
            "section_count": len(structured_doc.outline),
            "concept_count": len(context.concepts),
            "grounded_concept_count": len(context.concepts_with_evidence()),
            "evidence_count": len(context.evidence),
            "skill_count": len(context.skills),
            "formula_count": len(context.formulas),
            "prerequisite_count": len(context.prerequisites),
            "topic_count": len(context.topics),
            "knowledge_document_id": context.knowledge_document_id,
            "warnings": [w.code for w in structured_doc.warnings],
            "build_seconds": round(time.time() - started, 2),
            "reused": False,
        }

        logger.info(
            "Knowledge build for %s: %d pages, %d concepts (%d grounded), %d evidence in %.2fs",
            document_id,
            build["page_count"],
            build["concept_count"],
            build["grounded_concept_count"],
            build["evidence_count"],
            build["build_seconds"],
        )
        return build

    def load_existing(self, document_id: str) -> Optional[Dict[str, Any]]:
        """Return a summary for an already-built document, or ``None``."""
        context = self.context_repo.load_context(document_id)
        if context is None:
            return None
        structured = None
        try:
            structured = self.storage.load_structured_document(document_id)
        except Exception:  # pragma: no cover - corrupted cache must not hide the context
            logger.warning("Could not read structured document for %s", document_id)

        page_count = 0
        if structured:
            page_count = len(structured.get("pages", []) or [])

        return {
            "document_id": document_id,
            "filename": context.source_filename,
            "title": context.document_title,
            "status": "READY",
            "recovery_state": "COMPLETED",
            "page_count": page_count,
            "concept_count": len(context.concepts),
            "grounded_concept_count": len(context.concepts_with_evidence()),
            "evidence_count": len(context.evidence),
            "skill_count": len(context.skills),
            "formula_count": len(context.formulas),
            "prerequisite_count": len(context.prerequisites),
            "topic_count": len(context.topics),
            "knowledge_document_id": context.knowledge_document_id,
            "reused": True,
        }

    def get_context(self, document_id: str) -> LearningContext:
        context = self.context_repo.load_context(document_id)
        if context is None:
            raise KnowledgeNotFoundError(
                "No knowledge context has been built for this document yet. "
                "Upload the document first.",
                details={"document_id": document_id},
            )
        return context

    def get_retriever(self, document_id: str) -> EvidenceRetriever:
        """
        Build a retrieval index for ``document_id``.

        Requires the Phase 1 structured document because the index resolves page numbers
        and section titles from it.
        """
        context = self.get_context(document_id)

        structured = self.storage.load_structured_document(document_id)
        if not structured:
            raise KnowledgeNotFoundError(
                "The structured document backing this knowledge context is missing, so "
                "no source passages can be cited.",
                details={"document_id": document_id},
            )

        from schemas.document import StructuredDocument

        structured_doc = StructuredDocument.model_validate(structured)
        ekr = _EkrShim.from_context(context)
        return EvidenceRetriever(structured_doc, ekr)

    # ------------------------------------------------------------------
    # Steps
    # ------------------------------------------------------------------

    def _validate(self, file_bytes: bytes, filename: str):
        from phase5.validation.input_validator import InputValidator

        result = InputValidator().validate_file(file_bytes, filename)
        if not result.is_valid:
            raise UnsupportedDocumentError(
                "; ".join(result.errors) or f"'{filename}' could not be accepted.",
                details={
                    "filename": filename,
                    "errors": list(result.errors),
                    "recovery_classification": getattr(
                        result.recovery_classification, "value", str(result.recovery_classification)
                    ),
                },
            )
        return result

    def _ingest(self, file_bytes: bytes, filename: str, document_id: str):
        """
        Normalise any supported format and run Phase 1 over it.

        PDF-like inputs go through the real extraction pipeline. OOXML files fall back to
        the native reader when LibreOffice is unavailable, which still yields real blocks.
        """
        from ingestion.document_formats import to_structured_document

        return to_structured_document(
            file_bytes,
            filename,
            document_id,
            run_pdf_pipeline=self._run_phase1_from,
        )

    def _run_phase1_from(self, pdf_bytes: bytes, pdf_name: str, document_id: str):
        from ingestion.pipeline import IngestionPipeline

        pipeline = IngestionPipeline(storage=self.storage, db=self.db)
        try:
            structured_doc = pipeline.process_pdf_bytes(pdf_bytes, pdf_name, document_id)
        except Exception as exc:
            raise IngestionError(
                f"Phase 1 could not extract readable content from '{pdf_name}': {exc}",
                details={"document_id": document_id, "filename": pdf_name},
            ) from exc

        return structured_doc

    @staticmethod
    def _validate_structured(structured_doc) -> None:
        total_blocks = sum(len(p.blocks) for p in structured_doc.pages)
        if total_blocks == 0:
            raise IngestionError(
                "No text could be extracted from this document. If it is a scan, it needs "
                "OCR support; if it is empty, there is nothing to learn from.",
                details={
                    "document_id": structured_doc.document_id,
                    "page_count": len(structured_doc.pages),
                },
            )

        if getattr(structured_doc.metadata.processing_status, "value", None) == "failed":
            raise IngestionError(
                "Phase 1 reported the document as unreadable.",
                details={
                    "document_id": structured_doc.document_id,
                    "warnings": [w.code for w in structured_doc.warnings],
                },
            )

    @staticmethod
    def _run_phase2(structured_doc):
        from phase2.pipeline.runner import Phase2PipelineError, Phase2PipelineRunner

        try:
            return Phase2PipelineRunner().process(structured_doc)
        except Phase2PipelineError as exc:
            raise KnowledgeBuildError(
                f"Phase 2 could not build a knowledge representation from this document: "
                f"{exc.cause}",
                details={"stage": exc.stage, "document_id": structured_doc.document_id},
            ) from exc

    @staticmethod
    def _assert_grounded(context: LearningContext, structured_doc) -> None:
        """
        Refuse to hand back a context that cannot support grounded teaching.

        If concepts were extracted without explicit evidence bindings (e.g. from
        sparse slides or outline notes), attempt an automatic block-level evidence
        resolution pass against the real text before declaring the build ungrounded.
        """
        grounded = context.concepts_with_evidence()
        if grounded:
            return

        # Attempt automatic block-level evidence resolution
        from phase2.models import Evidence, EvidenceKindEnum, EvidenceLevelEnum, TextSpan

        for c_id, concept in list(context.concepts.items()):
            c_name = concept.canonical_name.lower()
            for page in getattr(structured_doc, "pages", []) or []:
                for block in getattr(page, "blocks", []) or []:
                    b_text = (block.content.text or "").strip()
                    if c_name and c_name in b_text.lower():
                        ev_id = f"ev_auto_{c_id}_{block.block_id}"
                        span_start = b_text.lower().find(c_name)
                        span_end = span_start + len(c_name)
                        ev = Evidence(
                            evidence_id=ev_id,
                            block_id=block.block_id,
                            span=TextSpan(start=max(0, span_start), end=max(span_start + 1, span_end)),
                            excerpt=b_text[:300],
                            level=EvidenceLevelEnum.STRONG_INFERRED,
                            kind=EvidenceKindEnum.EXPLICIT_STATEMENT,
                            source_confidence=0.85,
                        )
                        context.evidence[ev_id] = ev
                        if ev_id not in concept.evidence_ids:
                            concept.evidence_ids.append(ev_id)
                        if block.block_id not in concept.block_ids:
                            concept.block_ids.append(block.block_id)
                        if page.page_index not in concept.page_indices:
                            concept.page_indices.append(page.page_index)
                        if not concept.description:
                            concept.description = b_text[:200]
                        break
                if concept.evidence_ids:
                    break

        grounded = context.concepts_with_evidence()
        if not grounded:
            raise KnowledgeBuildError(
                "The document yielded no concept that is actually supported by its own text, "
                "so LearnSense cannot teach from it. The file may be mostly images, tables "
                "without captions, or a cover page.",
                details={
                    "document_id": structured_doc.document_id,
                    "total_concepts": len(context.concepts),
                    "pages": len(structured_doc.pages),
                },
            )


class _EkrShim:
    """
    Minimal EKR-shaped view over a persisted ``LearningContext``.

    The retriever only needs concepts, mentions and evidence, all of which the context
    already carries, so rebuilding the full EKR for retrieval would be wasteful.
    """

    def __init__(self, source_document_id: str, concepts, mentions, evidence) -> None:
        self.source_document_id = source_document_id
        self.concepts = concepts
        self.mentions = mentions
        self.evidence = evidence

    @classmethod
    def from_context(cls, context: LearningContext) -> "_EkrShim":
        evidence = list(context.evidence.values())

        # Mentions: one per (concept, evidence) pair, with the excerpt as the span.
        from phase2.models import ConceptMention, TextSpan

        mentions: List[ConceptMention] = []
        for concept in context.concepts.values():
            for ev_id in concept.evidence_ids:
                ev = context.evidence.get(ev_id)
                if ev is None:
                    continue
                excerpt = ev.excerpt or ""
                mentions.append(
                    ConceptMention(
                        mention_id=f"mn_{concept.concept_id}_{ev_id}",
                        concept_id=concept.concept_id,
                        block_id=ev.block_id,
                        span=TextSpan(start=0, end=max(0, len(excerpt))),
                        surface_form=concept.canonical_name,
                    )
                )

        return cls(
            source_document_id=context.document_id,
            concepts=list(context.concepts.values()),
            mentions=mentions,
            evidence=evidence,
        )

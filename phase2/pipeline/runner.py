"""
Pipeline Runner managing overall stage execution and stage/section level failure isolation.
Plan §21: Section-level or stage-level failure degrades gracefully to 'completed_with_warnings'.
"""

from typing import Dict, Any, List, Optional
from schemas.document import StructuredDocument
from phase2.models import (
    EducationalKnowledgeRepresentation,
    EducationalUnit,
    SectionStatus,
    SectionSemanticStatusEnum,
    WarningMessage,
)
from phase2.contract import validate_structured_document_input
from phase2.pipeline.stage1_normalize import run_stage1_normalize
from phase2.pipeline.stage2_context import run_stage2_context
from phase2.pipeline.stage3_segment import run_stage3_segmentation
from phase2.pipeline.stage4_candidates import extract_candidates
from phase2.pipeline.stage5_resolution import run_stage5_entity_resolution
from phase2.pipeline.stage6_assembly import run_stage6_object_assembly
from phase2.pipeline.stage7_relationships import run_stage7_relationship_extraction
from phase2.pipeline.stage8_graph import run_stage8_graph_construction
from phase2.pipeline.stage9_qc import run_stage9_qc
from phase2.adapters.nlp_adapters import Tier01DeterministicAdapter


class Phase2PipelineError(RuntimeError):
    """Raised when a Phase 2 stage fails in a way that invalidates the EKR."""

    def __init__(self, stage: str, cause: Exception):
        super().__init__(f"Phase 2 stage '{stage}' failed: {cause}")
        self.stage = stage
        self.cause = cause


class Phase2PipelineRunner:
    """
    Runs the nine-stage EKR pipeline over a Phase 1 ``StructuredDocument``.

    ``strict`` (the default) turns a failure of any structural stage into a
    :class:`Phase2PipelineError` instead of a warning. This matters: previously every
    stage exception was downgraded to a ``WarningMessage``, so a mis-wired adapter
    produced an EKR with zero units, zero skills and zero formulas that still reported
    ``status="completed"`` and passed QC. Downstream, that empty EKR surfaced as a blank
    lesson rather than an error, which is how placeholder content reached learners.

    Pass ``strict=False`` only for exploratory runs over deliberately partial documents.
    """

    def __init__(
        self,
        *,
        nlp_adapter: Optional[Tier01DeterministicAdapter] = None,
        strict: bool = True,
    ):
        if nlp_adapter is not None and not hasattr(nlp_adapter, "classify_text_role"):
            raise TypeError(
                "nlp_adapter must implement classify_text_role(); got "
                f"{type(nlp_adapter).__name__}. Pass it as the keyword argument "
                "'nlp_adapter=...'."
            )
        self.nlp_adapter = nlp_adapter or Tier01DeterministicAdapter()
        self.strict = strict

    def _fail(self, stage: str, exc: Exception, ekr: EducationalKnowledgeRepresentation):
        message = f"{type(exc).__name__}: {exc}"
        ekr.status = "failed"
        ekr.warnings.append(WarningMessage(code="STAGE_FAILURE", scope="document", message=f"{stage}: {message}"))
        if self.strict:
            raise Phase2PipelineError(stage, exc) from exc

    @staticmethod
    def _populate_sections(
        doc: StructuredDocument,
        units: List[EducationalUnit],
        ekr: EducationalKnowledgeRepresentation,
    ) -> None:
        """
        Derive ``ekr.sections`` from the real document outline and the units bound to it.

        The EKR schema carries a section list, but nothing populated it, so every
        downstream consumer (the Phase 3 adapter's topic map, section titles in
        citations, the learner's outline view) operated on an empty list.
        """
        titles: Dict[str, str] = {}
        pages: Dict[str, int] = {}

        def _walk(nodes) -> None:
            for node in nodes or []:
                titles[node.section_id] = node.title
                pages[node.section_id] = node.page_start
                _walk(getattr(node, "children", []) or [])

        _walk(getattr(doc, "outline", []) or [])

        counts: Dict[str, int] = {}
        for unit in units or []:
            # Sections without a heading are keyed "sec_page_<n>" by the segmenter, so
            # they simply never match a real outline title and are not emitted below.
            if not unit.section_id:
                continue
            counts[unit.section_id] = counts.get(unit.section_id, 0) + 1

        statuses: List[SectionStatus] = []
        for sec_id, title in titles.items():
            unit_count = counts.get(sec_id, 0)
            if unit_count == 0:
                # A heading with no bound content is not an educational section.
                continue
            statuses.append(
                SectionStatus(
                    section_id=sec_id,
                    semantic_status=SectionSemanticStatusEnum.OK,
                    warnings=[],
                )
            )

        if not statuses and counts:
            # Document had no outline but Phase 2 still segmented content.
            for sec_id in counts:
                statuses.append(
                    SectionStatus(
                        section_id=sec_id,
                        semantic_status=SectionSemanticStatusEnum.OK,
                        warnings=[],
                    )
                )

        ekr.sections = statuses

    def process(self, doc: StructuredDocument) -> EducationalKnowledgeRepresentation:
        # Validate contract
        contract_warnings = validate_structured_document_input(doc)

        ekr = EducationalKnowledgeRepresentation(
            knowledge_document_id=f"kr_{doc.document_id}",
            source_document_id=doc.document_id,
            status="completed"
        )

        for cw in contract_warnings:
            ekr.warnings.append(WarningMessage(code="CONTRACT_WARNING", scope="document", message=cw))

        # Stage 1: Normalize
        try:
            norm_doc = run_stage1_normalize(doc)
        except Exception as e:
            self._fail("stage1_normalize", e, ekr)
            return ekr

        # Stage 2: Context
        try:
            doc_ctx = run_stage2_context(norm_doc)
            ekr.document_profile = doc_ctx.profile
        except Exception as e:
            self._fail("stage2_context", e, ekr)
            doc_ctx = None

        # Stage 3: Segmentation & Roles
        try:
            units = run_stage3_segmentation(norm_doc, doc_ctx, self.nlp_adapter)
            ekr.educational_units = units
        except Exception as e:
            self._fail("stage3_segmentation", e, ekr)
            units = []

        # Record the document's section outline and per-section semantic status.
        self._populate_sections(doc, units, ekr)

        # Stage 4: Candidates
        try:
            candidates = extract_candidates(norm_doc, doc_ctx, units)
            ekr.skills = candidates.skills
            ekr.formulas = candidates.formulas
        except Exception as e:
            self._fail("stage4_candidates", e, ekr)
            candidates = None

        # Stage 5: Entity Resolution
        try:
            concepts, merge_records = run_stage5_entity_resolution(norm_doc, candidates)
            ekr.concepts = concepts
            ekr.merge_records = merge_records
            ekr.mentions = candidates.mentions
        except Exception as e:
            self._fail("stage5_entity_resolution", e, ekr)
            concepts = []

        # Stage 6: Object Assembly
        try:
            items = run_stage6_object_assembly(norm_doc, units, concepts, candidates)
            ekr.assessable_items = items
        except Exception as e:
            self._fail("stage6_object_assembly", e, ekr)

        # Stage 7: Relationships
        try:
            relationships = run_stage7_relationship_extraction(norm_doc, concepts, candidates)
        except Exception as e:
            self._fail("stage7_relationships", e, ekr)
            relationships = []

        # Stage 8: Graph Construction
        try:
            relationships, views = run_stage8_graph_construction(concepts, relationships)
            ekr.relationships = relationships
            ekr.views = views
            ekr.evidence = candidates.evidence
        except Exception as e:
            self._fail("stage8_graph", e, ekr)

        # Build block text map for Stage 9
        block_text_map = {b["block_id"]: b["text"] for b in norm_doc.semantic_blocks}

        # Stage 9: Semantic QC & Packaging
        ekr = run_stage9_qc(ekr, block_text_map)

        self._assert_usable(ekr, norm_doc)

        return ekr

    def _assert_usable(self, ekr, norm_doc: "NormalizedDocumentContext") -> None:
        """
        Reject an EKR that would silently starve the learning runtime.

        A document with extractable text must yield at least one educational unit and
        one concept. If it does not, the correct behaviour is a typed failure the API
        can report, not an empty knowledge map that a learner experiences as a blank
        lesson with no explanation.
        """
        if not self.strict:
            return

        usable_blocks = [
            b for b in norm_doc.semantic_blocks
            if b["included_in_semantic_flow"] and (b["text"] or "").strip()
        ]
        if not usable_blocks:
            # Nothing extractable at all: legitimately un-ingestible, but the Phase 1
            # status should already reflect that, so do not raise here.
            return

        missing = []
        if not ekr.educational_units:
            missing.append("educational_units")
        if not ekr.concepts:
            missing.append("concepts")
        if not ekr.evidence:
            missing.append("evidence")

        if missing:
            raise Phase2PipelineError(
                "stage9_qc",
                ValueError(
                    "Phase 2 produced no " + ", ".join(missing) + f" for a document with "
                    f"{len(usable_blocks)} extractable text block(s). The knowledge "
                    "representation is not usable for generation."
                ),
            )

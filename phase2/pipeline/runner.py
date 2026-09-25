"""
Pipeline Runner managing overall stage execution and stage/section level failure isolation.
Plan §21: Section-level or stage-level failure degrades gracefully to 'completed_with_warnings'.
"""

from typing import Dict, Any, Optional
from schemas.document import StructuredDocument
from phase2.models import EducationalKnowledgeRepresentation, SectionStatus, SectionSemanticStatusEnum, WarningMessage
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


class Phase2PipelineRunner:
    def __init__(self, nlp_adapter: Optional[Tier01DeterministicAdapter] = None):
        self.nlp_adapter = nlp_adapter or Tier01DeterministicAdapter()

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
            ekr.status = "failed"
            ekr.warnings.append(WarningMessage(code="STAGE1_FAILURE", scope="document", message=str(e)))
            return ekr

        # Stage 2: Context
        try:
            doc_ctx = run_stage2_context(norm_doc)
            ekr.document_profile = doc_ctx.profile
        except Exception as e:
            ekr.status = "completed_with_warnings"
            ekr.warnings.append(WarningMessage(code="STAGE2_FAILURE", scope="document", message=str(e)))
            doc_ctx = None

        # Stage 3: Segmentation & Roles
        try:
            units = run_stage3_segmentation(norm_doc, doc_ctx, self.nlp_adapter)
            ekr.educational_units = units
        except Exception as e:
            ekr.status = "completed_with_warnings"
            ekr.warnings.append(WarningMessage(code="STAGE3_FAILURE", scope="document", message=str(e)))
            units = []

        # Stage 4: Candidates
        try:
            candidates = extract_candidates(norm_doc, doc_ctx, units)
            ekr.skills = candidates.skills
            ekr.formulas = candidates.formulas
        except Exception as e:
            ekr.status = "completed_with_warnings"
            ekr.warnings.append(WarningMessage(code="STAGE4_FAILURE", scope="document", message=str(e)))

        # Stage 5: Entity Resolution
        try:
            concepts, merge_records = run_stage5_entity_resolution(norm_doc, candidates)
            ekr.concepts = concepts
            ekr.merge_records = merge_records
            ekr.mentions = candidates.mentions
        except Exception as e:
            ekr.status = "completed_with_warnings"
            ekr.warnings.append(WarningMessage(code="STAGE5_FAILURE", scope="document", message=str(e)))
            concepts = []

        # Stage 6: Object Assembly
        try:
            items = run_stage6_object_assembly(norm_doc, units, concepts, candidates)
            ekr.assessable_items = items
        except Exception as e:
            ekr.status = "completed_with_warnings"
            ekr.warnings.append(WarningMessage(code="STAGE6_FAILURE", scope="document", message=str(e)))

        # Stage 7: Relationships
        try:
            relationships = run_stage7_relationship_extraction(norm_doc, concepts, candidates)
        except Exception as e:
            ekr.status = "completed_with_warnings"
            ekr.warnings.append(WarningMessage(code="STAGE7_FAILURE", scope="document", message=str(e)))
            relationships = []

        # Stage 8: Graph Construction
        try:
            relationships, views = run_stage8_graph_construction(concepts, relationships)
            ekr.relationships = relationships
            ekr.views = views
            ekr.evidence = candidates.evidence
        except Exception as e:
            ekr.status = "completed_with_warnings"
            ekr.warnings.append(WarningMessage(code="STAGE8_FAILURE", scope="document", message=str(e)))

        # Build block text map for Stage 9
        block_text_map = {b["block_id"]: b["text"] for b in norm_doc.semantic_blocks}

        # Stage 9: Semantic QC & Packaging
        ekr = run_stage9_qc(ekr, block_text_map)

        return ekr

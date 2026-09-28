"""
Stage 3 — Segmentation and Semantic-Role Classification.
Classifies blocks/spans into educational units with semantic roles.
Plan §6.
"""

from typing import List
from phase2.models import EducationalUnit, SourceSpanReference, TextSpan
from phase2.pipeline.stage1_normalize import NormalizedDocumentContext
from phase2.pipeline.stage2_context import DocumentContext
from phase2.adapters.nlp_adapters import Tier01DeterministicAdapter
from phase2.utils.id_generator import generate_unit_id


def run_stage3_segmentation(
    norm_doc: NormalizedDocumentContext,
    doc_ctx: DocumentContext,
    nlp_adapter: Tier01DeterministicAdapter
) -> List[EducationalUnit]:
    units: List[EducationalUnit] = []
    unit_idx = 0

    for block in norm_doc.semantic_blocks:
        if not block["included_in_semantic_flow"]:
            continue

        text = block["text"]
        if not text or not text.strip():
            continue

        role = nlp_adapter.classify_text_role(text)

        unit_idx += 1
        # Blocks outside any heading (a document with no outline, or body text before the
        # first heading) still belong to a real, locatable group. Keying them by their
        # page keeps the section id traceable to the document instead of collapsing them
        # into an invented "sec_default" bucket that appears in API responses.
        page_index = block.get("page_index", 0)
        sec_id = block["section_id"] or f"sec_page_{page_index + 1}"
        u_id = generate_unit_id(norm_doc.doc_id, sec_id, unit_idx, role)

        unit = EducationalUnit(
            unit_id=u_id,
            unit_type=role,
            section_id=sec_id,
            source=[
                SourceSpanReference(
                    block_id=block["block_id"],
                    span=TextSpan(start=0, end=len(text))
                )
            ]
        )
        units.append(unit)

    return units

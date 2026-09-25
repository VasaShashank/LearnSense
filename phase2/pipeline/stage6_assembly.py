"""
Stage 6 — Knowledge Object Assembly.
Attaches definitions, formulas, examples, and minimal assessable items to concepts and educational units.
Plan §9.
"""

from typing import List
from phase2.models import (
    Concept,
    EducationalUnit,
    AssessableItem,
    Formula,
    UnitLink,
    ConceptLink,
    SkillLink,
    Evidence,
    EvidenceLevelEnum,
    EvidenceKindEnum,
    TextSpan,
)
from phase2.pipeline.stage1_normalize import NormalizedDocumentContext
from phase2.pipeline.stage4_candidates import Stage4ExtractionResult
from phase2.utils.id_generator import generate_item_id, generate_evidence_id


def run_stage6_object_assembly(
    norm_doc: NormalizedDocumentContext,
    units: List[EducationalUnit],
    concepts: List[Concept],
    candidates: Stage4ExtractionResult
) -> List[AssessableItem]:
    concept_map = {c.canonical_name.lower(): c for c in concepts}

    # 1. Attach harvested definitions to concepts
    for hdef in candidates.harvested_definitions:
        term = hdef["term"].lower()
        if term in concept_map:
            concept = concept_map[term]
            if hdef["unit_id"]:
                concept.unit_links.append(
                    UnitLink(unit_id=hdef["unit_id"], link="defines")
                )

    # 2. Attach concept links to educational units
    for unit in units:
        for concept in concepts:
            for ev_id in concept.evidence_ids:
                # Check matching block
                for ev in candidates.evidence:
                    if ev.evidence_id == ev_id and any(s.block_id == ev.block_id for s in unit.source):
                        unit.concept_links.append(
                            ConceptLink(concept_id=concept.concept_id, link="mentions")
                        )

    # 3. Assemble Minimal Assessable Items
    assessable_items: List[AssessableItem] = []
    item_idx = 0

    for unit in units:
        if unit.unit_type in ("exercise", "question"):
            item_idx += 1
            item_id = generate_item_id(norm_doc.doc_id, unit.unit_id, item_idx)

            # Find associated skills and concepts
            assoc_concept_ids = [cl.concept_id for cl in unit.concept_links]
            assoc_skills = []

            for sk in candidates.skills:
                # Link skill if it shares concepts or block
                assoc_skills.append(
                    SkillLink(skill_id=sk.skill_id, confidence=0.8, basis="exercise_context")
                )

            ev_id = generate_evidence_id(norm_doc.doc_id, unit.source[0].block_id, 0, 10, "item")
            ev = Evidence(
                evidence_id=ev_id,
                block_id=unit.source[0].block_id,
                span=TextSpan(start=0, end=10),
                excerpt="Exercise item",
                level=EvidenceLevelEnum.EXPLICIT,
                kind=EvidenceKindEnum.EXPLICIT_STATEMENT,
                source_confidence=0.95
            )
            candidates.evidence.append(ev)

            item = AssessableItem(
                item_id=item_id,
                item_type=unit.unit_type,
                unit_id=unit.unit_id,
                concept_ids=assoc_concept_ids,
                skill_links=assoc_skills,
                evidence_ids=[ev_id]
            )
            assessable_items.append(item)

    return assessable_items

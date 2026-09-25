"""
Stage 4 — Candidate Extraction.
Extracts concept mentions, skills (including explicit learning objectives), definitions, acronyms, glossaries, and formulas.
Plan §7.
"""

import re
from typing import Any, Dict, List, Tuple
from phase2.models import (
    ConceptMention,
    Skill,
    Formula,
    Evidence,
    EvidenceLevelEnum,
    EvidenceKindEnum,
    TextSpan,
    ActionCategoryEnum,
    ConfidenceBreakdown,
)
from phase2.pipeline.stage1_normalize import NormalizedDocumentContext
from phase2.pipeline.stage2_context import DocumentContext
from phase2.models import EducationalUnit
from phase2.utils.id_generator import (
    generate_mention_id,
    generate_skill_id,
    generate_evidence_id,
    generate_formula_id,
)

STOPWORDS = {
    "system", "method", "process", "thing", "item", "example", "chapter",
    "section", "figure", "table", "definition", "equation", "problem", "solution"
}


class Stage4ExtractionResult:
    def __init__(self):
        self.mentions: List[ConceptMention] = []
        self.skills: List[Skill] = []
        self.formulas: List[Formula] = []
        self.evidence: List[Evidence] = []
        self.harvested_definitions: List[Dict[str, Any]] = []
        self.acronyms: Dict[str, str] = {}


def extract_candidates(
    norm_doc: NormalizedDocumentContext,
    doc_ctx: DocumentContext,
    units: List[EducationalUnit]
) -> Stage4ExtractionResult:
    res = Stage4ExtractionResult()

    unit_by_block = {}
    for u in units:
        for s in u.source:
            unit_by_block[s.block_id] = u

    # Regex patterns for definitions, acronyms, formulas
    def_pattern = re.compile(r"([A-Z][A-Za-z0-9\s'-]{2,30})\s+(is defined as|refers to|is called)\s+(.+)", re.IGNORECASE)
    acronym_pattern = re.compile(r"([A-Z][A-Za-z0-9\s'-]{2,40})\s*\(([A-Z]{2,6})\)")
    formula_pattern = re.compile(r"([A-Za-z_]+)\s*=\s*([A-Za-z0-9\s\+\-\*\/\^\(\)]+)")

    for block in norm_doc.semantic_blocks:
        if not block["included_in_semantic_flow"]:
            continue

        text = block["text"]
        blk_id = block["block_id"]
        unit = unit_by_block.get(blk_id)
        unit_id = unit.unit_id if unit else None

        # 1. Harvest Acronyms
        for match in acronym_pattern.finditer(text):
            full_term, acr = match.group(1).strip(), match.group(2).strip()
            res.acronyms[acr] = full_term

        # 2. Harvest Definitions
        def_match = def_pattern.search(text)
        if def_match:
            term = def_match.group(1).strip()
            definition_text = def_match.group(3).strip()
            res.harvested_definitions.append({
                "term": term,
                "definition": definition_text,
                "block_id": blk_id,
                "unit_id": unit_id
            })

        # 3. Explicit Learning Objectives -> Skills
        if unit and unit.unit_type == "learning_objective" or "able to" in text.lower():
            # Heuristic action verb extraction
            action = ActionCategoryEnum.APPLY
            for act in ActionCategoryEnum:
                if act.value in text.lower():
                    action = act
                    break

            ev_id = generate_evidence_id(norm_doc.doc_id, blk_id, 0, len(text), "learning_objective")
            ev = Evidence(
                evidence_id=ev_id,
                block_id=blk_id,
                span=TextSpan(start=0, end=len(text)),
                excerpt=text,
                level=EvidenceLevelEnum.EXPLICIT,
                kind=EvidenceKindEnum.LEARNING_OBJECTIVE,
                source_confidence=block["confidence"]
            )
            res.evidence.append(ev)

            sk_id = generate_skill_id(norm_doc.doc_id, action.value, [blk_id])
            skill = Skill(
                skill_id=sk_id,
                action=action,
                statement=text,
                source_kind="explicit_objective",
                confidence=ConfidenceBreakdown(value=0.9),
                evidence_ids=[ev_id]
            )
            res.skills.append(skill)

        # 4. Formula Extraction
        if block["type"] == "equation" or formula_pattern.search(text):
            f_id = generate_formula_id(norm_doc.doc_id, blk_id, len(res.formulas) + 1)
            formula = Formula(
                formula_id=f_id,
                representation=text,
                source_unit_id=unit_id or f"u_{blk_id}"
            )
            res.formulas.append(formula)

        # 5. Extract Concept Mention Candidates
        words = re.findall(r"\b[A-Z][a-z0-9]+(?:\s+[A-Z][a-z0-9]+)*\b", text)
        for w in words:
            term = w.strip()
            if term.lower() in STOPWORDS or len(term) < 3:
                continue

            start = text.find(term)
            if start != -1:
                end = start + len(term)
                m_id = generate_mention_id(norm_doc.doc_id, blk_id, start, end)
                mention = ConceptMention(
                    mention_id=m_id,
                    concept_id="",  # Resolved in Stage 5
                    block_id=blk_id,
                    span=TextSpan(start=start, end=end),
                    surface_form=term,
                    unit_id=unit_id,
                    confidence=block["confidence"]
                )
                res.mentions.append(mention)

    return res

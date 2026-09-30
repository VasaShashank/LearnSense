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
    "section", "figure", "table", "definition", "equation", "problem", "solution",
    # Document boilerplate that capitalized-phrase matching otherwise promotes
    # into the concept graph (headers, footers, cover pages, exam furniture).
    "page", "pages", "paper", "annexure", "appendix", "syllabus", "curriculum",
    "textbook", "reference", "references", "bibliography", "index", "content",
    "contents", "preface", "foreword", "acknowledgement", "certificate",
    "university", "college", "school", "department", "institute", "board",
    "professor", "lecturer", "teacher", "student", "students", "author",
    "authors", "name", "names", "date", "dates", "time", "hours", "minutes",
    "marks", "mark", "total", "grade", "score", "question", "questions",
    "answer", "answers", "note", "notes", "remark", "remarks", "instruction",
    "instructions", "hour", "minute", "second", "year", "month", "day",
    "monday", "tuesday", "wednesday", "thursday", "friday", "saturday",
    "sunday", "january", "february", "march", "april", "may", "june",
    "july", "august", "september", "october", "november", "december",
}

# Determiners / quantifiers / interrogatives that must never begin a concept name.
# Without this, capitalised sentence openers ("The Zorblax Protocol", "What", "Every")
# are promoted straight into the EKR concept graph and pollute the learner's atlas.
LEADING_FUNCTION_WORDS = {
    "the", "a", "an", "this", "that", "these", "those", "its", "their", "our",
    "your", "his", "her", "each", "every", "all", "any", "some", "no", "one",
    "two", "three", "what", "which", "who", "whom", "whose", "when", "where",
    "why", "how", "if", "then", "than", "as", "at", "by", "for", "from", "in",
    "into", "of", "on", "or", "so", "to", "we", "you", "they", "he", "she", "it",
    "note", "see", "figure", "table", "exercise", "example", "summary", "overview",
    "introduction", "conclusion", "definition", "theorem", "lemma", "proof",
    "chapter", "section", "part", "unit", "lesson", "topic", "step", "rule",
    "using", "given", "let", "suppose", "consider", "recall", "remember", "prove",
}

# Trailing tokens stripped from a multi-word candidate before it is treated as a concept.
TRAILING_FUNCTION_WORDS = {"the", "a", "an", "of", "and", "or", "to", "in", "for", "is", "are"}


def _trim_candidate(term: str) -> str:
    """Strip leading determiners/interrogatives and dangling function words."""
    words = term.split()
    while words and words[0].lower() in LEADING_FUNCTION_WORDS:
        words = words[1:]
    while words and words[-1].lower() in TRAILING_FUNCTION_WORDS:
        words = words[:-1]
    if not words:
        return ""
    # Keep a single lower-cased preposition attached to a proper name (e.g. "Rules of Evidence")
    # but drop a dangling one.
    if len(words) > 1 and words[-1].lower() in {"of", "and", "or", "to", "in", "for"}:
        words = words[:-1]
    return " ".join(words)


def _is_single_common_word(term: str) -> bool:
    """Reject lone sentence-initial function words such as "What" or "The"."""
    if " " in term:
        return False
    return term.lower() in LEADING_FUNCTION_WORDS


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
            term = _trim_candidate(w.strip())
            if not term:
                continue
            if term.lower() in STOPWORDS or len(term) < 3:
                continue
            if _is_single_common_word(term):
                continue
            # A trimmed candidate must still occur verbatim so the Evidence span
            # remains a real substring of the block (Phase 2 QC enforces this).
            start = text.find(term)
            if start == -1:
                continue
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

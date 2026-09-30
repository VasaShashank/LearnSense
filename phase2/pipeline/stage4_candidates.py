"""
Stage 4 — Candidate Extraction.
Extracts concept mentions, skills (including explicit learning objectives), definitions, acronyms, glossaries, and formulas.
Plan §7.
"""

import re
from typing import Any, Dict, List, Set, Tuple
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

# A term must appear at least this many times (case-insensitive) in the whole
# document to count as a teachable concept. Real subject terms recur; slide
# titles, table headers and incidental proper nouns appear once.
MIN_TERM_OCCURRENCES = 2

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


# Block types / roles that carry page furniture rather than subject matter.
# Mining these is what previously turned table headers ("Entity", "PK",
# "Purpose"), slide titles and author names into "concepts".
_NON_PROSE_BLOCK_TYPES = {
    "table", "caption", "figure", "header", "footer", "page_number",
    "watermark", "toc_entry", "index_entry", "footnote", "code", "image",
}
_NON_PROSE_ROLES = {
    "table", "caption", "figure", "header", "footer", "page_number",
    "watermark", "footnote", "reference", "metadata",
}

# A citation line: "Malkov, Y. A., & Yashunin, D. A. (2020). ..." or
# "Selinger, P. G., et al. (1979). ... ACM SIGMOD."
_CITATION_MARKERS = (
    " et al.", " et al,", "&", "doi:", "isbn", "arxiv",
    "sigmod", "neurips", "tpami", "vldb", "www.", "http://", "https://",
    "journal of", "proceedings of", "pp.", "vol.", "editors",
)


def _is_title_block(text: str) -> bool:
    """
    True when a block looks like a document/slide title rather than prose.

    Titles are short, have no sentence-ending punctuation, and contain few
    words. A single-line paragraph ("A limit describes ...") ends in a full
    stop and is clearly prose, so it is never mistaken for a title.
    """
    stripped = text.strip()
    if not stripped or len(stripped) > 200:
        return False
    lines = [ln for ln in stripped.splitlines() if ln.strip()]
    if not lines:
        return False
    # A title may span a couple of lines but is never a run-on paragraph.
    if len(" ".join(lines).split()) > 14:
        return False
    # Prose ends sentences; titles do not.
    if stripped.endswith((".", ";", ",")):
        return False
    return True


def _is_markdown_table(text: str) -> bool:
    """True for pipe-delimited table blocks (rows, headers, separators)."""
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    if not lines:
        return False
    pipe_lines = sum(1 for ln in lines if "|" in ln)
    if pipe_lines < 2:
        return False
    # A header separator row like "| --- | --- |" is a definitive signal.
    return any(re.fullmatch(r"\|[\s\-:|]+\|", ln) for ln in lines) or (
        pipe_lines / len(lines) >= 0.6
    )


def _is_bibliography_entry(text: str) -> bool:
    """True for reference-list lines (author surname + year + venue)."""
    lowered = text.lower()
    if re.search(r"\(\s*(19|20)\d{2}\s*\)", lowered):
        # A year in parentheses plus citation vocabulary is a reference.
        if any(m in lowered for m in _CITATION_MARKERS):
            return True
        # "Malkov, Y. A." style author initials are conclusive.
        if re.search(r"\b[a-z]+,\s+[a-z]\.\s*[a-z]?\.?", lowered):
            return True
    return False


# Person-name shapes seen in academic front matter:
#   "Revanth Vishnu Reddy C B (1RV24CS227)"
#   "Team: Revanth Vishnu Reddy C B, Punith A M, ..."
#   "Ramakrishnan, R., & Gehrke, J."
_ID_CODE = re.compile(r"\(\s*[A-Z0-9]{6,}\s*\)")
_INITIAL_TOKEN = re.compile(r"\b[A-Z]\b")


def _person_name_keys(text: str) -> Set[str]:
    """
    Normalized keys for tokens that are part of a personal name.

    Two shapes are recognised: an institutional-ID suffix
    (``Revanth Vishnu Reddy C B (1RV24CS227)``) and a comma-introduced
    author list (``Ramakrishnan, R., & Gehrke, J.``).
    """
    keys: Set[str] = set()
    for m in _ID_CODE.finditer(text):
        before = text[: m.start()]
        # Walk back over the name tokens preceding the ID.
        for tok in re.findall(r"[A-Z][A-Za-z']+|[A-Z]\b", before[-80:]):
            if len(tok) >= 2 and tok.lower() not in STOPWORDS:
                keys.add(tok.lower())
    # Author lists: "Surname, A. B., & Surname, C."
    for m in re.finditer(r"\b([A-Z][a-z]{2,}),\s+[A-Z]\.", text):
        keys.add(m.group(1).lower())
    return keys


def _is_person_name(term: str, person_keys: Set[str]) -> bool:
    """True when every content word of the term is a known person-name token."""
    words = [w for w in term.split() if w.lower() not in LEADING_FUNCTION_WORDS]
    if not words:
        return False
    return all(w.lower() in person_keys for w in words)


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

    # --- Document-level scan -------------------------------------------------
    # Concept quality depends on document-wide signals, so compute them before
    # walking blocks: which blocks are bibliography/table furniture, and how
    # often each candidate term actually recurs.
    lowercase_corpus = ""
    # The document's own title is not subject matter: a document titled
    # "Akasic-Hybrid — Presenter's Guide" must not turn "Akasic" into a topic.
    doc_title = ""
    try:
        meta_title = getattr(getattr(norm_doc, "doc", None), "metadata", None)
        raw_title = getattr(meta_title, "title", None)
        # ``title`` is a TitleMetadata object (or a plain dict in older payloads).
        if hasattr(raw_title, "value"):
            raw_title = raw_title.value
        elif isinstance(raw_title, dict):
            raw_title = raw_title.get("value")
        if isinstance(raw_title, str):
            doc_title = raw_title.strip().lower()
    except Exception:
        doc_title = ""

    # The opening line of a document is its title, not subject matter. Collect it
    # in addition to the metadata title, because the two often differ (metadata
    # may say "Presenter's Guide" while line 1 reads "Akasic-Hybrid ...").
    # A title token only disqualifies a term that never recurs in prose.
    opening_title_tokens: Set[str] = set()
    for b in norm_doc.semantic_blocks:
        for ln in b["text"].splitlines():
            s = ln.strip()
            if s:
                if len(s) <= 120:
                    for tok in re.findall(r"[A-Za-z][A-Za-z'-]+", s):
                        if tok.lower() not in STOPWORDS:
                            opening_title_tokens.add(tok.lower())
                break
        break
    if doc_title:
        for tok in re.findall(r"[A-Za-z][A-Za-z'-]+", doc_title):
            if tok.lower() not in STOPWORDS:
                opening_title_tokens.add(tok.lower())
    skipped_block_ids: Set[str] = set()
    person_name_keys: Set[str] = set()
    # Tokens that appear only inside short standalone lines (titles/furniture).
    furniture_keys: Set[str] = set()

    first_block_id = None
    for b in norm_doc.semantic_blocks:
        first_block_id = b["block_id"]
        break

    for block in norm_doc.semantic_blocks:
        text = block["text"]
        btype = (block.get("type") or "").lower()
        brole = (block.get("role") or "").lower()

        # The document's first block is a title block only when it is SHORT,
        # title-shaped and NOT a declared heading. A heading block names a real
        # topic ("Chapter 1: Force and Motion"), so it is always mined.
        if (
            block["block_id"] == first_block_id
            and btype != "heading"
            and brole != "heading"
            and _is_title_block(text)
        ):
            skipped_block_ids.add(block["block_id"])
            continue

        # Only prose-like blocks describe teachable subject matter. Tables,
        # captions, headers/footers, page furniture and code yield column
        # labels, slide titles and author names, never concepts.
        if btype in _NON_PROSE_BLOCK_TYPES or brole in _NON_PROSE_ROLES:
            skipped_block_ids.add(block["block_id"])
            continue

        if _is_markdown_table(text):
            skipped_block_ids.add(block["block_id"])
            continue
        if _is_bibliography_entry(text):
            skipped_block_ids.add(block["block_id"])
            continue

        person_name_keys.update(_person_name_keys(text))

        # Short standalone lines are titles/furniture. Record their tokens so an
        # UNDECLARED candidate matching one of them is dropped.
        for ln in text.splitlines():
            s = ln.strip()
            if s and len(s) <= 60:
                for tok in re.findall(r"[A-Za-z][A-Za-z'-]+", s):
                    if tok.lower() not in STOPWORDS:
                        furniture_keys.add(tok.lower())

    # Recurrence is measured over PROSE only. Counting table/citation text would
    # let a term look common purely because it repeats across table headers.
    lowercase_corpus = "\n".join(
        b["text"] for b in norm_doc.semantic_blocks
        if b["block_id"] not in skipped_block_ids
    ).lower()

    for block in norm_doc.semantic_blocks:
        if not block["included_in_semantic_flow"]:
            continue
        if block["block_id"] in skipped_block_ids:
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
        is_heading = (block.get("type") or "").lower() == "heading"
        # A term occupying a line by itself is a declared topic, even when the
        # whole document arrives as one paragraph block (common for PDFs).
        # The line must be SHORT and contain nothing but the term, so a long
        # run-on title line never "declares" the first word of itself.
        line_standalone: Set[str] = set()
        for ln in text.splitlines():
            s = ln.strip()
            if not s or len(s) > 60:
                continue
            # Reject lines that carry sentence punctuation or extra prose.
            if s.endswith((".", ",", ";", ":", "!", "?")) or '"' in s or "(" in s:
                continue
            line_standalone.add(s.lower())
        words = re.findall(r"\b[A-Z][a-z0-9]+(?:\s+[A-Z][a-z0-9]+)*\b", text)
        for w in words:
            term = _trim_candidate(w.strip())
            if not term:
                continue
            if term.lower() in STOPWORDS or len(term) < 3:
                continue
            if _is_single_common_word(term):
                continue
            if _is_person_name(term, person_name_keys):
                continue
            # Accept when the document declares the term (heading block, or a
            # standalone line). Otherwise require recurrence in PROSE: an inline
            # capitalized phrase seen once is incidental, not a topic.
            declared = is_heading or term.lower() in line_standalone
            if not declared:
                # A word appearing only in the document title / short furniture
                # lines is not subject matter ("Akasic" in "Akasic-Hybrid ...").
                if term.lower() in furniture_keys or term.lower() in opening_title_tokens:
                    continue
                if lowercase_corpus.count(term.lower()) < MIN_TERM_OCCURRENCES:
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

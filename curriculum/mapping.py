"""
Mapping extracted educational content onto canonical curriculum concepts (Person 2).

Input boundary
--------------
This module never parses a PDF and never re-extracts text.  It consumes the
artifacts the existing pipeline already produces:

* Phase 1 ``StructuredDocument`` (``schemas.document``) for raw text passages,
  and
* Phase 3 ``LearningContext`` / Phase 2 ``EducationalKnowledgeRepresentation``
  for already-extracted concept candidates with their evidence.

Deterministic matching only
---------------------------
Matching is rule based (the table below).  No embeddings, no LLM, no paid API is
involved, so the same inputs always give the same output and the evaluation in
``evaluation/curriculum_eval.py`` is reproducible.  A semantic model should only
be added if this table is shown to fail on held-out examples that matter.

``match_strength`` is a **deterministic match-strength score, not a probability
and not a calibrated accuracy**.  Its meaning is exactly the rule that produced
it:

====== =============================================== ================== =======
Rule   Condition                                        Kind               Base
====== =============================================== ================== =======
R1     surface == normalized canonical name              ``canonical_name``  1.00
R2     surface == normalized alias                       ``alias``           0.92
R3     surface occurs on term boundaries inside a name   ``alias``           0.80
       or alias and covers >= 60% of its length
R4     token Jaccard(surface, name) >= 0.60              ``alias``           0.60
                                                          + 0.30 * jaccard
R5     wording identical after notation is stripped and  ``notation_variant`` 0.75
       the surface contains notation characters
====== =============================================== ================== =======

Two documented bonuses are then applied for *text passages* (never for extracted
concepts, where the label itself is the evidence):

* ``+0.10`` definition position — the sentence starts with the matched surface;
* ``+0.05`` subject context — the passage's subject hint equals the concept's
  subject.

The final strength is clamped to ``[0, 1]``.

Decision thresholds (also documented, also fixed):

* ``ACCEPTED``  — best strength >= 0.90 and the runner-up is at least 0.05 lower;
* ``UNCERTAIN`` — best strength >= 0.60 but not decisive;
* ``UNMAPPED``  — nothing at or above 0.60.

Unmapped content stays unmapped.  The mapper does not force every passage onto a
concept; that would manufacture a graph the source never supported.
"""

from __future__ import annotations

import hashlib
import re
from enum import Enum
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from pydantic import BaseModel, ConfigDict, Field

from curriculum.ids import excerpt_hash, stable_key_from_name
from curriculum.models import (
    CanonicalConcept,
    ClassLevel,
    ConceptLifecycleStatus,
    CurriculumGraph,
    SourceRef,
    Subject,
    utc_now_iso,
)
from curriculum.normalization import (
    contains_term,
    fold_superscripts,
    is_notation_variant,
    jaccard_similarity,
    normalize_term,
    split_sentences,
    strip_notation,
    tokenize,
)

__all__ = [
    "ACCEPTED_MIN_STRENGTH",
    "ContentMapper",
    "ContentMappingResult",
    "DECISIVENESS_MARGIN",
    "ExtractedConceptCandidate",
    "MappingCandidate",
    "MappingContext",
    "MappingStatus",
    "MatchKind",
    "UNCERTAIN_MIN_STRENGTH",
    "ConceptMatch",
    "ProposedConcept",
    "passages_from_learning_context",
    "passages_from_structured_document",
]

#: Decision thresholds.  Changing these changes reported quality metrics, so they
#: are named constants rather than magic numbers scattered through the code.
ACCEPTED_MIN_STRENGTH = 0.90
UNCERTAIN_MIN_STRENGTH = 0.60
DECISIVENESS_MARGIN = 0.05

_DEFINITION_POSITION_BONUS = 0.10
_SUBJECT_CONTEXT_BONUS = 0.05

_BASE_STRENGTH = {
    "canonical_name": 1.00,
    "alias": 0.92,
    "containment": 0.80,
    "notation_variant": 0.75,
    "token_overlap": 0.60,
}

# Block types that carry readable curriculum prose.  Figures, captions, headers,
# footers and page furniture are skipped: they are layout, not content.
_TEXT_BLOCK_TYPES = {"heading", "paragraph", "list_item", "table", "equation", "code"}

# Roles that are page furniture even when the block type looks textual.
_SKIPPED_ROLES = {"header", "footer", "page_number", "watermark", "sidebar"}

# Upper bound on a single passage, so a 40-page wall of text does not become one
# unreviewable mapping unit.
MAX_PASSAGE_CHARS = 900

_SUBJECT_HINT_WORDS = {
    "physics": Subject.PHYSICS,
    "chemistry": Subject.CHEMISTRY,
    "mathematics": Subject.MATHEMATICS,
    "maths": Subject.MATHEMATICS,
    "math": Subject.MATHEMATICS,
}


class MappingStatus(str, Enum):
    """Outcome for one extracted concept or one text passage."""

    ACCEPTED = "accepted"
    UNCERTAIN = "uncertain"
    UNMAPPED = "unmapped"


class MatchKind(str, Enum):
    """Which rule produced a match.  Mirrors the rule table in the module docstring."""

    CANONICAL_NAME = "canonical_name"
    ALIAS = "alias"
    NOTATION_VARIANT = "notation_variant"


class MappingContext(BaseModel):
    """Document-level context used to constrain and rank candidates."""

    model_config = ConfigDict(extra="forbid")

    document_id: str = ""
    subject_hint: Optional[Subject] = None
    class_levels: List[ClassLevel] = Field(default_factory=list)
    chapter_id: Optional[str] = None
    source_kind: str = "structured_document"


class ConceptMatch(BaseModel):
    """One canonical concept that a surface form could refer to."""

    model_config = ConfigDict(extra="forbid")

    concept_id: str
    canonical_name: str
    matched_surface: str
    match_kind: MatchKind
    match_strength: float = Field(ge=0.0, le=1.0)
    applied_rules: List[str] = Field(default_factory=list)
    evidence_locator: Optional[str] = None
    excerpt: str = ""

    def sort_key(self) -> Tuple[float, str]:
        return (-self.match_strength, self.concept_id)


class ProposedConcept(BaseModel):
    """
    A brand new canonical concept proposed for teacher review.

    Deliberately *not* auto-accepted: an extracted claim becomes a curriculum
    fact only after a human says so.
    """

    model_config = ConfigDict(extra="forbid")

    name: str
    description: str = ""
    subject: Subject
    chapter_id: Optional[str] = None
    class_levels: List[ClassLevel] = Field(default_factory=list)
    tags: List[str] = Field(default_factory=list)
    aliases: List[str] = Field(default_factory=list)
    suggested_stable_key: str = ""
    source_refs: List[SourceRef] = Field(default_factory=list)
    extracted_type: str = ""

    @classmethod
    def build(
        cls,
        *,
        name: str,
        subject: Subject,
        description: str = "",
        chapter_id: Optional[str] = None,
        class_levels: Optional[Sequence[ClassLevel]] = None,
        tags: Optional[Sequence[str]] = None,
        aliases: Optional[Sequence[str]] = None,
        source_refs: Optional[Sequence[SourceRef]] = None,
        extracted_type: str = "",
    ) -> "ProposedConcept":
        return cls(
            name=name.strip(),
            description=description,
            subject=subject,
            chapter_id=chapter_id,
            class_levels=list(class_levels or []),
            tags=list(tags or []),
            aliases=[alias for alias in (aliases or []) if normalize_term(alias)],
            suggested_stable_key=stable_key_from_name(name, chapter_id),
            source_refs=list(source_refs or []),
            extracted_type=extracted_type,
        )


class MappingCandidate(BaseModel):
    """Result for a single input item (an extracted concept or a passage)."""

    model_config = ConfigDict(extra="forbid")

    item_id: str
    source_kind: str
    label: str = ""
    status: MappingStatus
    matches: List[ConceptMatch] = Field(default_factory=list)
    proposed_concept: Optional[ProposedConcept] = None
    reason: str = ""
    source_refs: List[SourceRef] = Field(default_factory=list)

    @property
    def predicted_concept_id(self) -> Optional[str]:
        """Top-ranked canonical id regardless of confidence (None when unmapped)."""
        return self.matches[0].concept_id if self.matches else None

    @property
    def is_decisive(self) -> bool:
        return self.status == MappingStatus.ACCEPTED


class ContentMappingResult(BaseModel):
    """Reproducible mapping run."""

    model_config = ConfigDict(extra="forbid")

    curriculum_id: str
    document_id: str = ""
    input_kind: str
    created_at: str = Field(default_factory=utc_now_iso)
    context: MappingContext = Field(default_factory=MappingContext)
    candidates: List[MappingCandidate] = Field(default_factory=list)
    summary: Dict[str, int] = Field(default_factory=dict)
    fingerprint: str = ""

    def predicted_pairs(self) -> List[Tuple[str, Optional[str]]]:
        """``(item_id, predicted_concept_id)`` for every item, in input order."""
        return [(candidate.item_id, candidate.predicted_concept_id) for candidate in self.candidates]

    def status_counts(self) -> Dict[str, int]:
        counts = {status.value: 0 for status in MappingStatus}
        for candidate in self.candidates:
            counts[candidate.status.value] += 1
        return counts


class Passage(BaseModel):
    """A unit of source text with enough provenance to be re-found later."""

    model_config = ConfigDict(extra="forbid")

    passage_id: str
    source_id: str
    text: str
    locator: Optional[str] = None
    page_index: Optional[int] = None
    section_id: Optional[str] = None
    section_title: Optional[str] = None
    block_ids: List[str] = Field(default_factory=list)

    def source_ref(self) -> SourceRef:
        return SourceRef.build(
            source_id=self.source_id,
            locator=self.locator,
            excerpt=self.text[:240],
            page_index=self.page_index,
            block_ids=self.block_ids,
            section_title=self.section_title,
            section_id=self.section_id,
        )


class ExtractedConceptCandidate(BaseModel):
    """An already-extracted concept (Phase 2/3) waiting to be mapped or adopted."""

    model_config = ConfigDict(extra="forbid")

    item_id: str
    name: str
    aliases: List[str] = Field(default_factory=list)
    description: str = ""
    extracted_type: str = ""
    document_id: str = ""
    source_refs: List[SourceRef] = Field(default_factory=list)

    @classmethod
    def from_concept_view(cls, view: Any, document_id: str = "") -> "ExtractedConceptCandidate":
        """Build from a ``phase3.knowledge.phase2_adapter.ConceptView``."""
        refs = [
            SourceRef.build(
                source_id=document_id,
                locator=f"pages:{','.join(str(p + 1) for p in (view.page_indices or [])) or 'unknown'}",
                excerpt=(view.description or "")[:240] or None,
                page_index=(view.page_indices or [None])[0],
                block_ids=list(view.block_ids or []),
                section_title=(view.section_titles or [None])[0],
                evidence_ids=list(view.evidence_ids or []),
            )
        ] if document_id else []
        return cls(
            item_id=view.concept_id,
            name=view.canonical_name,
            aliases=list(view.aliases or []),
            description=view.description or "",
            extracted_type=view.type,
            document_id=document_id,
            source_refs=refs,
        )


# --------------------------------------------------------------------- passages
def _passage_id(document_id: str, section_id: str, page_index: int, ordinal: int) -> str:
    raw = f"{document_id}::{section_id}::{page_index}::{ordinal}"
    return "pg_" + hashlib.sha256(raw.encode("utf-8")).hexdigest()[:12]


def _value_of(node: Any) -> str:
    return node.value if hasattr(node, "value") else str(node)


def passages_from_structured_document(document: Any) -> List[Passage]:
    """
    Read passages out of an existing Phase 1 ``StructuredDocument``.

    This is a *reader*, not a parser: it walks ``pages[].blocks[]`` in reading
    order, skips non-text furniture, and groups consecutive blocks that share a
    section into passages of at most :data:`MAX_PASSAGE_CHARS` characters.

    Accepts either the model itself or the JSON dict ``DocumentStorage`` returns,
    in which case it is validated against the Phase 1 schema first -- the schema
    is the boundary, so a malformed document fails loudly instead of being
    partially read.
    """
    if isinstance(document, dict):
        from schemas.document import StructuredDocument

        try:
            document = StructuredDocument.model_validate(document)
        except Exception as exc:  # pragma: no cover - defensive, surfaced to caller
            raise ValueError(
                f"Input is not a valid StructuredDocument: {exc}"
            ) from exc
    if getattr(document, "pages", None) is None:
        raise ValueError("Input has no 'pages'; expected a Phase 1 StructuredDocument")

    document_id = getattr(document, "document_id", "") or ""
    section_titles: Dict[str, str] = {}

    def _walk(nodes: Iterable[Any]) -> None:
        for node in nodes or []:
            section_titles[node.section_id] = node.title
            _walk(getattr(node, "children", []) or [])

    _walk(getattr(document, "outline", []) or [])

    passages: List[Passage] = []
    buffer: List[str] = []
    buffer_blocks: List[str] = []
    current_page: Optional[int] = None
    current_section: Optional[str] = None
    ordinal = 0

    def _flush() -> None:
        nonlocal buffer, buffer_blocks, ordinal
        text = " ".join(part.strip() for part in buffer if part.strip()).strip()
        if text:
            ordinal += 1
            section_id = current_section or ""
            locator_parts = []
            if current_page is not None:
                locator_parts.append(f"p.{current_page + 1}")
            if section_id:
                locator_parts.append(f"§{section_titles.get(section_id, section_id)}")
            passages.append(
                Passage(
                    passage_id=_passage_id(document_id, section_id, current_page or -1, ordinal),
                    source_id=document_id,
                    text=text,
                    locator=" ".join(locator_parts) or None,
                    page_index=current_page,
                    section_id=section_id or None,
                    section_title=section_titles.get(section_id),
                    block_ids=list(buffer_blocks),
                )
            )
        buffer = []
        buffer_blocks = []

    for page in sorted(getattr(document, "pages", []) or [], key=lambda p: p.page_index):
        for block in sorted(page.blocks or [], key=lambda b: b.reading_order):
            if _value_of(block.type) not in _TEXT_BLOCK_TYPES:
                continue
            if (getattr(block, "role", "") or "") in _SKIPPED_ROLES:
                continue
            text = (block.content.text or "").strip() if block.content else ""
            if not text:
                continue
            section_id = block.section_id or ""
            same_bucket = (
                current_section == section_id
                and current_page == page.page_index
                and sum(len(part) for part in buffer) + len(text) <= MAX_PASSAGE_CHARS
            )
            if not same_bucket and buffer:
                _flush()
            current_section = section_id
            current_page = page.page_index
            buffer.append(text)
            buffer_blocks.append(block.block_id)
    _flush()
    return passages


def passages_from_learning_context(context: Any) -> List[Passage]:
    """
    Read passages out of an existing Phase 3 ``LearningContext``.

    Uses the concept evidence the ingestion pipeline already grounded, so the
    provenance (pages, blocks, sections) is the real document location rather
    than a re-derived guess.
    """
    document_id = getattr(context, "document_id", "") or ""
    passages: List[Passage] = []
    for index, view in enumerate(sorted(context.concepts.values(), key=lambda c: c.concept_id), start=1):
        texts: List[str] = []
        if view.description:
            texts.append(view.description)
        for evidence in (context.evidence or {}).values():
            if evidence.evidence_id in (view.evidence_ids or []) and evidence.excerpt:
                texts.append(evidence.excerpt)
        text = " ".join(dict.fromkeys(texts)).strip()
        if not text:
            continue
        page_index = (view.page_indices or [None])[0]
        passages.append(
            Passage(
                passage_id=_passage_id(document_id, view.concept_id, page_index if page_index is not None else -1, index),
                source_id=document_id,
                text=text,
                locator=f"pages:{','.join(str(p + 1) for p in view.page_indices) or 'unknown'}",
                page_index=page_index,
                section_title=(view.section_titles or [None])[0],
                block_ids=list(view.block_ids or []),
            )
        )
    return passages


def infer_subject_hint(*texts: str) -> Optional[Subject]:
    """
    Best-effort subject inference from a document title / filename.

    Returns ``None`` when nothing or several subjects are mentioned, because a
    wrong subject hint silently filters out the right candidates.
    """
    found = set()
    for text in texts:
        lowered = (text or "").casefold()
        for word, subject in _SUBJECT_HINT_WORDS.items():
            if re.search(rf"\b{re.escape(word)}\b", lowered):
                found.add(subject)
    if len(found) == 1:
        return next(iter(found))
    return None


def _apply_rules(surface_key: str, target_key: str, kind: str) -> Optional[Tuple[float, MatchKind, str]]:
    """
    Apply the documented rule table (R1-R5) to one surface/target pair.

    Returns ``(base_strength, match_kind, rule_id)`` or ``None`` when no rule
    fires.  Shared by the indexed text mapper and the concept-level matcher so
    the two can never drift apart.
    """
    if not surface_key or not target_key:
        return None

    if surface_key == target_key:
        if kind == "canonical_name":
            return _BASE_STRENGTH["canonical_name"], MatchKind.CANONICAL_NAME, "R1"
        return _BASE_STRENGTH["alias"], MatchKind.ALIAS, "R2"

    if contains_term(target_key, surface_key) or contains_term(surface_key, target_key):
        longer, shorter = (
            (target_key, surface_key) if len(target_key) >= len(surface_key) else (surface_key, target_key)
        )
        if len(shorter) / max(len(longer), 1) >= 0.60:
            return _BASE_STRENGTH["containment"], MatchKind.ALIAS, "R3"

    jaccard = jaccard_similarity(tokenize(surface_key), tokenize(target_key))
    if jaccard >= 0.60:
        strength = min(1.0, _BASE_STRENGTH["token_overlap"] + 0.30 * jaccard)
        return strength, MatchKind.ALIAS, "R4"

    if is_notation_variant(surface_key):
        if strip_notation(fold_superscripts(surface_key)) == strip_notation(fold_superscripts(target_key)):
            return _BASE_STRENGTH["notation_variant"], MatchKind.NOTATION_VARIANT, "R5"

    return None


def score_surface_against_concept(
    surface: str, concept: CanonicalConcept
) -> Optional[ConceptMatch]:
    """
    Best rule-table match of a free-text surface against one canonical concept.

    Used by the simulator bridge and by callers that already know which concept
    they are comparing against.  No subject/context bonus is applied: the caller
    supplies the surface, and the score should reflect only the surface itself.
    """
    surface_key = normalize_term(surface)
    if not surface_key:
        return None
    best: Optional[ConceptMatch] = None
    for entry in concept.surface_keys():
        scored = _apply_rules(surface_key, entry["surface"], entry["kind"])
        if scored is None:
            continue
        base, kind, rule = scored
        match = ConceptMatch(
            concept_id=concept.concept_id,
            canonical_name=concept.name,
            matched_surface=surface,
            match_kind=kind,
            match_strength=round(base, 4),
            applied_rules=[rule],
        )
        if best is None or match.sort_key() < best.sort_key():
            best = match
    return best


# ---------------------------------------------------------------------- mapper
class _SurfaceEntry(BaseModel):
    """Internal index row."""

    model_config = ConfigDict(extra="ignore")

    concept_id: str
    canonical_name: str
    surface: str
    original: str
    kind: str
    subject: str


class ContentMapper:
    """
    Deterministic content -> canonical concept mapper.

    The canonical concept set is fixed at construction, so a mapping run is a
    pure function of (graph, inputs) and can be replayed byte for byte.
    """

    def __init__(
        self,
        graph: CurriculumGraph,
        context: Optional[MappingContext] = None,
    ):
        self.graph = graph
        self.context = context or MappingContext()
        self._entries: List[_SurfaceEntry] = []
        self._first_token_index: Dict[str, List[int]] = {}
        self._build_index()

    # ------------------------------------------------------------------ index
    def _build_index(self) -> None:
        entries: List[_SurfaceEntry] = []
        for concept_id in self.graph.concept_ids():
            concept = self.graph.concepts[concept_id]
            if _status(concept.status) == ConceptLifecycleStatus.DEPRECATED.value:
                continue
            for entry in concept.surface_keys():
                entries.append(
                    _SurfaceEntry(
                        concept_id=concept.concept_id,
                        canonical_name=concept.name,
                        surface=entry["surface"],
                        original=entry["original"],
                        kind=entry["kind"],
                        subject=concept.subject_value,
                    )
                )
        entries.sort(key=lambda entry: (entry.surface, entry.concept_id))
        self._entries = entries
        index: Dict[str, List[int]] = {}
        for position, entry in enumerate(entries):
            first_token = entry.surface.split(" ")[0]
            index.setdefault(first_token, []).append(position)
        self._first_token_index = index

    @property
    def indexed_surface_count(self) -> int:
        return len(self._entries)

    # ---------------------------------------------------------------- scoring
    def _candidate_entries(self, sentence_key: str) -> List[_SurfaceEntry]:
        """Prune the index by first token, then return deterministic candidates."""
        tokens = set(sentence_key.split())
        positions: List[int] = []
        for first_token in sorted(self._first_token_index):
            if first_token in tokens:
                positions.extend(self._first_token_index[first_token])
        return [self._entries[position] for position in sorted(set(positions))]

    def _score_surface(self, surface_key: str, entry: _SurfaceEntry) -> Optional[Tuple[float, MatchKind, str]]:
        """Apply the documented rule table to one surface/entry pair."""
        return _apply_rules(surface_key, entry.surface, entry.kind)

    def _matches_for_surface(
        self,
        surface_key: str,
        surface_original: str,
        *,
        locator: Optional[str] = None,
        excerpt: str = "",
        definition_bonus: float = 0.0,
        bonus_rules: Optional[List[str]] = None,
        subject_hint: Optional[str] = None,
    ) -> List[ConceptMatch]:
        best_per_concept: Dict[str, ConceptMatch] = {}
        for entry in self._candidate_entries(surface_key):
            scored = self._score_surface(surface_key, entry)
            if scored is None:
                continue
            base, kind, rule = scored
            bonuses = definition_bonus
            applied = [rule] + list(bonus_rules or [])
            if subject_hint is not None and entry.subject == subject_hint:
                bonuses += _SUBJECT_CONTEXT_BONUS
                applied.append("subject_context")
            strength = min(1.0, base + bonuses)
            match = ConceptMatch(
                concept_id=entry.concept_id,
                canonical_name=entry.canonical_name,
                matched_surface=surface_original,
                match_kind=kind,
                match_strength=round(strength, 4),
                applied_rules=applied,
                evidence_locator=locator,
                excerpt=excerpt,
            )
            existing = best_per_concept.get(entry.concept_id)
            if existing is None or match.sort_key() < existing.sort_key():
                best_per_concept[entry.concept_id] = match
        return sorted(best_per_concept.values(), key=lambda match: match.sort_key())

    # ------------------------------------------------------------- decisioning
    @staticmethod
    def decide(matches: Sequence[ConceptMatch]) -> Tuple[MappingStatus, str]:
        """Apply the documented decision thresholds to a ranked match list."""
        if not matches:
            return MappingStatus.UNMAPPED, "no canonical name or alias matched"
        best = matches[0].match_strength
        runner_up = matches[1].match_strength if len(matches) > 1 else 0.0
        if best < UNCERTAIN_MIN_STRENGTH:
            return (
                MappingStatus.UNMAPPED,
                f"best match strength {best:.2f} is below the {UNCERTAIN_MIN_STRENGTH:.2f} floor",
            )
        if best >= ACCEPTED_MIN_STRENGTH and (best - runner_up) >= DECISIVENESS_MARGIN:
            return (
                MappingStatus.ACCEPTED,
                f"decisive match at strength {best:.2f} (runner-up {runner_up:.2f})",
            )
        if len(matches) > 1 and (best - runner_up) < DECISIVENESS_MARGIN:
            alternatives = ", ".join(match.concept_id for match in matches[1:3])
            return (
                MappingStatus.UNCERTAIN,
                f"{len(matches)} plausible concepts within {DECISIVENESS_MARGIN:.2f} of each other "
                f"(also: {alternatives})",
            )
        return (
            MappingStatus.UNCERTAIN,
            f"best match strength {best:.2f} is below the {ACCEPTED_MIN_STRENGTH:.2f} acceptance threshold",
        )

    # ------------------------------------------------------------ public API
    def map_passages(self, passages: Sequence[Passage]) -> ContentMappingResult:
        """Map raw source text passages onto canonical concepts."""
        subject_hint = self.context.subject_hint.value if self.context.subject_hint else None
        candidates: List[MappingCandidate] = []
        for passage in passages:
            sentence_matches: List[ConceptMatch] = []
            for index, sentence in enumerate(split_sentences(passage.text), start=1):
                sentence_key = normalize_term(sentence)
                if not sentence_key:
                    continue
                locator = f"{passage.locator or passage.passage_id}#s{index}"
                definition_bonus = 0.0
                bonus_rules: List[str] = []
                if self._leading_surface(sentence_key):
                    definition_bonus = _DEFINITION_POSITION_BONUS
                    bonus_rules.append("definition_position")
                for entry in self._candidate_entries(sentence_key):
                    if not contains_term(sentence_key, entry.surface):
                        continue
                    sentence_matches.extend(
                        self._matches_for_surface(
                            entry.surface,
                            entry.original,
                            locator=locator,
                            excerpt=sentence,
                            definition_bonus=definition_bonus,
                            bonus_rules=bonus_rules,
                            subject_hint=subject_hint,
                        )
                    )
            # Keep the strongest match per concept across the whole passage.
            best_per_concept: Dict[str, ConceptMatch] = {}
            for match in sentence_matches:
                existing = best_per_concept.get(match.concept_id)
                if existing is None or match.sort_key() < existing.sort_key():
                    best_per_concept[match.concept_id] = match
            matches = sorted(best_per_concept.values(), key=lambda match: match.sort_key())
            status, reason = self.decide(matches)
            candidates.append(
                MappingCandidate(
                    item_id=passage.passage_id,
                    source_kind="text_passage",
                    label=passage.text[:120],
                    status=status,
                    matches=matches,
                    reason=reason,
                    source_refs=[passage.source_ref()],
                )
            )
        return self._result("text_passage", candidates)

    def _leading_surface(self, sentence_key: str) -> str:
        """Longest indexed surface that starts the sentence (definition position)."""
        first_word = sentence_key.split(" ")[0]
        best = ""
        for position in self._first_token_index.get(first_word, []):
            surface = self._entries[position].surface
            if sentence_key.startswith(surface) and len(surface) > len(best):
                best = surface
        return best

    def map_extracted_concepts(
        self, extracted: Sequence[ExtractedConceptCandidate]
    ) -> ContentMappingResult:
        """
        Map already-extracted concepts (Phase 2/3) onto canonical concepts.

        Items that match nothing are reported ``UNMAPPED`` with a
        :class:`ProposedConcept` for teacher review — they are *not* silently
        created as canonical concepts.
        """
        candidates: List[MappingCandidate] = []
        for item in extracted:
            surfaces = [item.name] + list(item.aliases)
            best_per_concept: Dict[str, ConceptMatch] = {}
            for surface in surfaces:
                surface_key = normalize_term(surface)
                if not surface_key:
                    continue
                for match in self._matches_for_surface(surface_key, surface):
                    existing = best_per_concept.get(match.concept_id)
                    if existing is None or match.sort_key() < existing.sort_key():
                        best_per_concept[match.concept_id] = match
            matches = sorted(best_per_concept.values(), key=lambda match: match.sort_key())
            status, reason = self.decide(matches)
            proposed = None
            if status == MappingStatus.UNMAPPED:
                subject = self.context.subject_hint or Subject.PHYSICS
                proposed = ProposedConcept.build(
                    name=item.name,
                    subject=subject,
                    description=item.description,
                    chapter_id=self.context.chapter_id,
                    class_levels=self.context.class_levels,
                    aliases=item.aliases,
                    source_refs=item.source_refs,
                    extracted_type=item.extracted_type,
                )
                reason = f"{reason}; proposing a new canonical concept for review"
            candidates.append(
                MappingCandidate(
                    item_id=item.item_id,
                    source_kind="extracted_concept",
                    label=item.name,
                    status=status,
                    matches=matches,
                    proposed_concept=proposed,
                    reason=reason,
                    source_refs=item.source_refs,
                )
            )
        return self._result("extracted_concept", candidates)

    # --------------------------------------------------------------- packaging
    def _result(self, input_kind: str, candidates: List[MappingCandidate]) -> ContentMappingResult:
        counts = {status.value: 0 for status in MappingStatus}
        for candidate in candidates:
            counts[candidate.status.value] += 1
        summary = {
            "total": len(candidates),
            "accepted": counts[MappingStatus.ACCEPTED.value],
            "uncertain": counts[MappingStatus.UNCERTAIN.value],
            "unmapped": counts[MappingStatus.UNMAPPED.value],
            "proposed_concepts": sum(1 for c in candidates if c.proposed_concept is not None),
        }
        result = ContentMappingResult(
            curriculum_id=self.graph.curriculum_id,
            document_id=self.context.document_id,
            input_kind=input_kind,
            context=self.context,
            candidates=candidates,
            summary=summary,
        )
        result.fingerprint = self.fingerprint(result)
        return result

    @staticmethod
    def fingerprint(result: ContentMappingResult) -> str:
        """
        Deterministic checksum over a mapping run.

        Audit timestamps are excluded, so re-running the mapper on the same
        inputs yields the same fingerprint and runs can be diffed.
        """
        payload = {
            "curriculum_id": result.curriculum_id,
            "document_id": result.document_id,
            "input_kind": result.input_kind,
            "context": result.context.model_dump(mode="json"),
            "candidates": [
                {
                    "item_id": candidate.item_id,
                    "status": candidate.status.value,
                    "reason": candidate.reason,
                    "matches": [match.model_dump(mode="json") for match in candidate.matches],
                    "proposed": (
                        candidate.proposed_concept.model_dump(mode="json")
                        if candidate.proposed_concept
                        else None
                    ),
                }
                for candidate in result.candidates
            ],
        }
        import json

        canonical = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
        return "mp_" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]


def _status(status: Any) -> str:
    return status.value if hasattr(status, "value") else str(status)


def reference_excerpt_hash(text: str) -> str:
    """Re-export so callers building evaluation fixtures hash excerpts consistently."""
    return excerpt_hash(text)

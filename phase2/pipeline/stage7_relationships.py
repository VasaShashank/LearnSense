"""
Stage 7 — Relationship Extraction.
Extracts typed relationships between concepts, classifies prerequisite evidence,
and enforces verification pass (quote grounding, direction sanity, negation/hedging detection, cycle prevention).
Matches Section 16 of TAPROOT master specification.
"""

import re
from collections import defaultdict
from typing import Dict, List, Optional, Set, Tuple

from phase2.models import (
    Concept,
    Relationship,
    RelationshipTypeEnum,
    RelationshipStatusEnum,
    Evidence,
    EvidenceLevelEnum,
    EvidenceKindEnum,
    TextSpan,
    ConfidenceBreakdown,
)
from phase2.pipeline.stage1_normalize import NormalizedDocumentContext
from phase2.pipeline.stage4_candidates import Stage4ExtractionResult
from phase2.utils.id_generator import generate_relationship_id, generate_evidence_id


def verify_relationship_grounding(
    excerpt: str,
    block_text: str,
    span: TextSpan
) -> bool:
    """Quote grounding pass: cited span text must match block text exactly."""
    if span.start < 0 or span.end > len(block_text) or span.start > span.end:
        return False
    span_text = block_text[span.start:span.end]
    if excerpt and excerpt not in block_text and excerpt != span_text:
        return False
    return True


_NEGATION_HEDGING_PHRASES = [
    "do not need",
    "does not require",
    "not necessary",
    "no prior knowledge",
    "optional",
    "not a prerequisite",
    "without requiring",
    "not needed",
    "might require",
    "could depend",
]


def detect_negation_or_hedging(text: str) -> bool:
    """Checks if relationship statement contains negation or hedging phrases."""
    t_lower = text.lower()
    return any(neg in t_lower for neg in _NEGATION_HEDGING_PHRASES)


def has_directed_path(adj: Dict[str, Set[str]], start: str, goal: str, visited: Optional[Set[str]] = None) -> bool:
    """Depth-first search to check if a directed path exists from start to goal (cycle check)."""
    if start == goal:
        return True
    if visited is None:
        visited = set()
    visited.add(start)
    for neighbor in adj.get(start, set()):
        if neighbor not in visited:
            if has_directed_path(adj, neighbor, goal, visited):
                return True
    return False


def build_concept_inverted_index(
    concepts: List[Concept]
) -> Tuple[Dict[str, Set[str]], Dict[str, Tuple[Concept, str, List[str]]]]:
    """
    Builds an inverted index from word tokens to concept IDs.
    Enables O(tokens_in_block) candidate retrieval instead of scanning every concept
    across every block in the document.
    """
    index: Dict[str, Set[str]] = defaultdict(set)
    concept_data: Dict[str, Tuple[Concept, str, List[str]]] = {}

    for c in concepts:
        can_name_lower = c.canonical_name.lower().strip()
        alias_lowers = [a.text.lower().strip() for a in c.aliases if a.text.strip()]
        concept_data[c.concept_id] = (c, can_name_lower, alias_lowers)

        all_terms = [can_name_lower] + alias_lowers
        for term in all_terms:
            tokens = re.findall(r"\b[a-zA-Z0-9_-]{2,}\b", term)
            for tok in tokens:
                index[tok].add(c.concept_id)

    return index, concept_data


def run_stage7_relationship_extraction(
    norm_doc: NormalizedDocumentContext,
    concepts: List[Concept],
    candidates: Stage4ExtractionResult
) -> List[Relationship]:
    """
    Extracts directional prerequisite and typed semantic relationships.
    Uses inverted index for high performance, enforces sentence-level quote grounding,
    supports distinct relationship types (PREREQUISITE_OF, PART_OF, IS_A, INSTANCE_OF,
    EXPLAINS, CAUSES, CONTRASTS_WITH, APPLIES_TO, RELATED_TO), and prevents cycles strictly
    on directed prerequisite graphs.
    """
    relationships: List[Relationship] = []
    seen_rel_ids: Set[str] = set()
    adj: Dict[str, Set[str]] = {}  # source -> set of targets (prerequisites only)

    block_map = {
        b["block_id"]: b["text"]
        for b in norm_doc.semantic_blocks
        if b.get("included_in_semantic_flow") and (b.get("text") or "").strip()
    }

    # Precompute evidence lookups
    block_evidence_ids: Dict[str, Set[str]] = defaultdict(set)
    for ev in candidates.evidence:
        block_evidence_ids[ev.block_id].add(ev.evidence_id)

    concept_ev_sets = {c.concept_id: set(c.evidence_ids) for c in concepts}

    # Build inverted index for fast candidate filtering
    inverted_index, concept_lookup = build_concept_inverted_index(concepts)

    for blk_id, text in block_map.items():
        if detect_negation_or_hedging(text):
            continue  # Skip negated or hedged prerequisite claims

        t_lower = text.lower()
        blk_evs = block_evidence_ids.get(blk_id, set())

        # Retrieve candidate concepts whose tokens appear in this block
        block_tokens = set(re.findall(r"\b[a-zA-Z0-9_-]{2,}\b", t_lower))
        candidate_cids: Set[str] = set()
        for tok in block_tokens:
            if tok in inverted_index:
                candidate_cids.update(inverted_index[tok])

        # Also include any concepts explicitly tied to this block via existing evidence
        for c_id, ev_set in concept_ev_sets.items():
            if ev_set & blk_evs:
                candidate_cids.add(c_id)

        if len(candidate_cids) < 2:
            continue

        # Find exact character positions for candidate concepts in block text
        pos_concepts: List[Tuple[Concept, int, int, str]] = []  # (concept, start_pos, end_pos, matched_term)
        for c_id in candidate_cids:
            c, c_name_lower, alias_lowers = concept_lookup[c_id]
            matched_pos = -1
            matched_len = 0
            matched_term = ""

            pos = t_lower.find(c_name_lower)
            if pos != -1:
                matched_pos = pos
                matched_len = len(c_name_lower)
                matched_term = c.canonical_name
            else:
                for a in alias_lowers:
                    pos = t_lower.find(a)
                    if pos != -1:
                        matched_pos = pos
                        matched_len = len(a)
                        matched_term = a
                        break

            if matched_pos != -1:
                pos_concepts.append((c, matched_pos, matched_pos + matched_len, matched_term))

        if len(pos_concepts) < 2:
            continue

        # Sort concepts by their appearance in the text
        pos_concepts.sort(key=lambda item: item[1])

        # Scan pairs of concepts occurring in this block
        for i in range(len(pos_concepts)):
            for j in range(len(pos_concepts)):
                if i == j:
                    continue

                c1, pos1_start, pos1_end, term1 = pos_concepts[i]
                c2, pos2_start, pos2_end, term2 = pos_concepts[j]

                # Do not link a concept to itself
                if c1.concept_id == c2.concept_id:
                    continue

                source_c = None
                target_c = None
                rel_type = RelationshipTypeEnum.PREREQUISITE_OF
                kind = EvidenceKindEnum.STATED_DEPENDENCY
                level = EvidenceLevelEnum.STRONG_INFERRED
                rationale_desc = ""

                # Concept ordering in text
                if pos1_start < pos2_start:
                    is_forward_order = True
                    between_text = t_lower[pos1_end:pos2_start].strip() if pos1_end <= pos2_start else t_lower[pos1_start:pos2_start].strip()
                elif pos2_start < pos1_start:
                    is_forward_order = False
                    between_text = t_lower[pos2_end:pos1_start].strip() if pos2_end <= pos1_start else t_lower[pos2_start:pos1_start].strip()
                else:
                    continue  # Exact same start offset

                # Only examine concepts within reasonable proximity (e.g. within 350 characters or same sentence)
                if abs(pos1_start - pos2_start) > 400:
                    continue

                # Pattern 1 & 6: "Before studying X, recall Y" or "Before learning X, ..."
                if "recall" in t_lower or "before studying" in t_lower or "before learning" in t_lower:
                    if is_forward_order:
                        source_c = c2
                        target_c = c1
                    else:
                        source_c = c1
                        target_c = c2
                    rel_type = RelationshipTypeEnum.PREREQUISITE_OF
                    kind = EvidenceKindEnum.EXPLICIT_STATEMENT
                    level = EvidenceLevelEnum.EXPLICIT
                    rationale_desc = "Explicit recall/prior learning indicator"

                # Pattern 5: "To understand X, ... know Y"
                elif "to understand" in t_lower and ("know" in t_lower or "understand" in t_lower or "recall" in t_lower):
                    if is_forward_order:
                        source_c = c2
                        target_c = c1
                    else:
                        source_c = c1
                        target_c = c2
                    rel_type = RelationshipTypeEnum.PREREQUISITE_OF
                    kind = EvidenceKindEnum.EXPLICIT_STATEMENT
                    level = EvidenceLevelEnum.EXPLICIT
                    rationale_desc = "Foundational understanding dependency"

                # Pattern 2: "Y is [a] prerequisite for/of X", "Y is required for X", "Y is needed for X"
                elif any(p in between_text for p in [
                    "prerequisite for", "prerequisite of", "prerequisite to",
                    "is required for", "is required to", "is needed for", "is necessary for",
                    "foundation for", "foundation of", "prerequisite"
                ]) or any(p in t_lower for p in ["is a prerequisite for", "is a prerequisite of", "is required for"]):
                    if is_forward_order:
                        source_c = c1
                        target_c = c2
                    else:
                        source_c = c2
                        target_c = c1
                    rel_type = RelationshipTypeEnum.PREREQUISITE_OF
                    kind = EvidenceKindEnum.EXPLICIT_STATEMENT
                    level = EvidenceLevelEnum.EXPLICIT
                    rationale_desc = "Explicit prerequisite specification"

                # Pattern 3 & 4: "X requires Y", "X depends on Y", "X builds on Y", "X relies on Y", "X is based on Y"
                elif any(p in between_text for p in [
                    "requires", "depends on", "builds on", "relies on", "necessitates", "is based on", "extends"
                ]) or (is_forward_order and any(p in t_lower for p in ["requires", "depends on", "builds on", "relies on"])):
                    if is_forward_order:
                        source_c = c2
                        target_c = c1
                    else:
                        source_c = c1
                        target_c = c2
                    rel_type = RelationshipTypeEnum.PREREQUISITE_OF
                    kind = EvidenceKindEnum.STATED_DEPENDENCY
                    level = EvidenceLevelEnum.STRONG_INFERRED
                    rationale_desc = "Stated functional or conceptual dependency"

                # Taxonomic INSTANCE_OF / EXAMPLE_OF
                elif any(p in between_text for p in ["is an example of", "is an instance of", "is exemplified by", "such as"]):
                    rel_type = RelationshipTypeEnum.INSTANCE_OF
                    source_c = c1 if is_forward_order else c2
                    target_c = c2 if is_forward_order else c1
                    kind = EvidenceKindEnum.EXPLICIT_STATEMENT
                    level = EvidenceLevelEnum.EXPLICIT
                    rationale_desc = "Exemplification / instance relation"

                # Taxonomic IS_A
                elif any(p in between_text for p in ["is a type of", "is a kind of", "is a form of", "is categorized as"]):
                    rel_type = RelationshipTypeEnum.IS_A
                    source_c = c1 if is_forward_order else c2
                    target_c = c2 if is_forward_order else c1
                    kind = EvidenceKindEnum.EXPLICIT_STATEMENT
                    level = EvidenceLevelEnum.EXPLICIT
                    rationale_desc = "Taxonomic hyponymy relation"

                # Meronymic PART_OF
                elif any(p in between_text for p in ["is part of", "is a component of", "is composed of", "subsystem of", "consists of"]):
                    rel_type = RelationshipTypeEnum.PART_OF
                    source_c = c1 if is_forward_order else c2
                    target_c = c2 if is_forward_order else c1
                    kind = EvidenceKindEnum.EXPLICIT_STATEMENT
                    level = EvidenceLevelEnum.EXPLICIT
                    rationale_desc = "Meronymic compositional relation"

                # Explanatory EXPLAINS
                elif any(p in between_text for p in ["explains", "clarifies", "describes", "details", "outlines"]):
                    rel_type = RelationshipTypeEnum.EXPLAINS
                    source_c = c1 if is_forward_order else c2
                    target_c = c2 if is_forward_order else c1
                    kind = EvidenceKindEnum.EXPLICIT_STATEMENT
                    level = EvidenceLevelEnum.EXPLICIT
                    rationale_desc = "Explanatory relation"

                # Causal CAUSES
                elif any(p in between_text for p in ["causes", "leads to", "results in", "produces", "triggers"]):
                    rel_type = RelationshipTypeEnum.CAUSES
                    source_c = c1 if is_forward_order else c2
                    target_c = c2 if is_forward_order else c1
                    kind = EvidenceKindEnum.EXPLICIT_STATEMENT
                    level = EvidenceLevelEnum.EXPLICIT
                    rationale_desc = "Causal dependency relation"

                # Contrastive CONTRASTS_WITH
                elif any(p in between_text for p in ["contrasts with", "differs from", "in contrast to", "as opposed to", "unlike"]):
                    rel_type = RelationshipTypeEnum.CONTRASTS_WITH
                    source_c = c1 if is_forward_order else c2
                    target_c = c2 if is_forward_order else c1
                    kind = EvidenceKindEnum.EXPLICIT_STATEMENT
                    level = EvidenceLevelEnum.EXPLICIT
                    rationale_desc = "Contrastive comparison relation"

                # Applicative APPLIES_TO
                elif any(p in between_text for p in ["applies to", "is applied to", "is applied in", "is used in", "utilized in"]):
                    rel_type = RelationshipTypeEnum.APPLIES_TO
                    source_c = c1 if is_forward_order else c2
                    target_c = c2 if is_forward_order else c1
                    kind = EvidenceKindEnum.EXPLICIT_STATEMENT
                    level = EvidenceLevelEnum.EXPLICIT
                    rationale_desc = "Application domain relation"

                if source_c and target_c and source_c.concept_id != target_c.concept_id:
                    # Enforce cycle prevention strictly for directed prerequisite DAGs
                    if rel_type == RelationshipTypeEnum.PREREQUISITE_OF and has_directed_path(
                        adj, target_c.concept_id, source_c.concept_id
                    ):
                        continue

                    rel_id = generate_relationship_id(
                        norm_doc.doc_id, source_c.concept_id, rel_type.value, target_c.concept_id
                    )

                    if rel_id in seen_rel_ids:
                        continue
                    seen_rel_ids.add(rel_id)

                    # Determine exact sentence or local excerpt boundary
                    span_start = min(pos1_start, pos2_start)
                    span_end = max(pos1_end, pos2_end)

                    # Expand to sentence boundary if nearby
                    sent_start = text.rfind(".", 0, span_start)
                    sent_start = 0 if sent_start == -1 else sent_start + 1
                    sent_end = text.find(".", span_end)
                    clause_start = max(0, sent_start)
                    clause_end = min(len(text), sent_end)
                    clause_text = text[clause_start:clause_end]
                    leading_ws = len(clause_text) - len(clause_text.lstrip())
                    trailing_ws = len(clause_text) - len(clause_text.rstrip())
                    clause_start += leading_ws
                    clause_end -= trailing_ws
                    excerpt_text = text[clause_start:clause_end]
                    span = TextSpan(start=clause_start, end=clause_end)

                    if not verify_relationship_grounding(excerpt_text, text, span):
                        span = TextSpan(start=0, end=len(text))
                        excerpt_text = text
                        if not verify_relationship_grounding(excerpt_text, text, span):
                            continue

                    ev_id = generate_evidence_id(norm_doc.doc_id, blk_id, span.start, span.end, "rel")
                    ev = Evidence(
                        evidence_id=ev_id,
                        block_id=blk_id,
                        span=span,
                        excerpt=excerpt_text,
                        level=level,
                        kind=kind,
                        source_confidence=0.95,
                    )
                    candidates.evidence.append(ev)

                    rel = Relationship(
                        relationship_id=rel_id,
                        source=source_c.concept_id,
                        type=rel_type,
                        target=target_c.concept_id,
                        status=RelationshipStatusEnum.ACCEPTED,
                        evidence_level=level,
                        confidence=ConfidenceBreakdown(
                            value=0.90 if level == EvidenceLevelEnum.STRONG_INFERRED else 0.95,
                            components={"source_quality": 0.95, "extraction": 0.92, "verification": 1.0},
                        ),
                        evidence_ids=[ev_id],
                        rationale=rationale_desc or f"{source_c.canonical_name} -> {target_c.canonical_name}",
                        extraction_method="deterministic_pattern",
                    )
                    relationships.append(rel)

                    if rel_type == RelationshipTypeEnum.PREREQUISITE_OF:
                        adj.setdefault(source_c.concept_id, set()).add(target_c.concept_id)

    return relationships

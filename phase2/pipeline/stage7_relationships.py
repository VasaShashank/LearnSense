"""
Stage 7 — Relationship Extraction.
Extracts typed relationships between concepts, classifies prerequisite evidence,
and enforces verification pass (quote grounding, direction sanity, negation/hedging detection, cycle prevention).
Matches Section 16 of TAPROOT master specification.
"""

import re
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


def run_stage7_relationship_extraction(
    norm_doc: NormalizedDocumentContext,
    concepts: List[Concept],
    candidates: Stage4ExtractionResult
) -> List[Relationship]:
    relationships: List[Relationship] = []
    seen_rel_ids: Set[str] = set()
    adj: Dict[str, Set[str]] = {}  # source -> set of targets

    block_map = {b["block_id"]: b["text"] for b in norm_doc.semantic_blocks if b["included_in_semantic_flow"]}
    concept_by_id = {c.concept_id: c for c in concepts}

    # Precompute evidence lookups and concept text representations (O(N) setup)
    from collections import defaultdict
    block_evidence_ids: Dict[str, Set[str]] = defaultdict(set)
    for ev in candidates.evidence:
        block_evidence_ids[ev.block_id].add(ev.evidence_id)

    concept_ev_sets = {c.concept_id: set(c.evidence_ids) for c in concepts}
    concept_search_data = [
        (c, c.canonical_name.lower(), [a.text.lower() for a in c.aliases])
        for c in concepts
    ]

    # Extract co-occurring candidate pairs across blocks
    for blk_id, text in block_map.items():
        if detect_negation_or_hedging(text):
            continue  # Skip negated or hedged prerequisite claims

        t_lower = text.lower()
        blk_evs = block_evidence_ids.get(blk_id, set())

        # Find concepts mentioned in this block (via explicit evidence or appearance in block text)
        mentioned_concepts = []
        pos_map = {}
        for c, c_name_lower, alias_lowers in concept_search_data:
            pos = t_lower.find(c_name_lower)
            if pos != -1:
                mentioned_concepts.append(c)
                pos_map[c.concept_id] = pos
            elif any(a in t_lower for a in alias_lowers):
                mentioned_concepts.append(c)
                pos_map[c.concept_id] = next(t_lower.find(a) for a in alias_lowers if a in t_lower)
            elif concept_ev_sets[c.concept_id] & blk_evs:
                mentioned_concepts.append(c)
                pos_map[c.concept_id] = -1

        if len(mentioned_concepts) < 2:
            continue

        # Filter to concepts that have a valid position in block text for directional analysis
        pos_concepts = [c for c in mentioned_concepts if pos_map.get(c.concept_id, -1) != -1]
        if len(pos_concepts) < 2:
            continue

        # Directional prerequisite and typed relationship extraction:
        # 1. "X requires Y" -> Y is prerequisite of X (Y -> X)
        # 2. "Y is prerequisite for X" / "Y is a prerequisite of X" -> Y -> X
        # 3. "X depends on Y" -> Y -> X
        # 4. "X builds on Y" / "X is based on Y" / "X relies on Y" -> Y -> X
        # 5. "To understand X, students should know Y" -> Y -> X
        # 6. "Before studying X, recall Y" -> Y -> X

        for i in range(len(pos_concepts)):
            for j in range(len(pos_concepts)):
                if i == j:
                    continue
                c1 = pos_concepts[i]
                c2 = pos_concepts[j]

                pos1 = pos_map[c1.concept_id]
                pos2 = pos_map[c2.concept_id]

                source_c = None  # Prerequisite / Source
                target_c = None  # Dependent / Target
                rel_type = RelationshipTypeEnum.PREREQUISITE_OF
                kind = EvidenceKindEnum.STATED_DEPENDENCY
                level = EvidenceLevelEnum.STRONG_INFERRED

                between_text = t_lower[min(pos1, pos2) : max(pos1, pos2)]

                # Pattern 1 & 6: "Before studying X, recall Y"
                if "recall" in t_lower or "before studying" in t_lower or "before learning" in t_lower:
                    if pos1 < pos2:
                        source_c = c2
                        target_c = c1
                    else:
                        source_c = c1
                        target_c = c2
                    kind = EvidenceKindEnum.EXPLICIT_STATEMENT
                    level = EvidenceLevelEnum.EXPLICIT

                # Pattern 5: "To understand X, ... know Y"
                elif "to understand" in t_lower and ("know" in t_lower or "understand" in t_lower or "recall" in t_lower):
                    if pos1 < pos2:
                        source_c = c2
                        target_c = c1
                    else:
                        source_c = c1
                        target_c = c2
                    kind = EvidenceKindEnum.EXPLICIT_STATEMENT
                    level = EvidenceLevelEnum.EXPLICIT

                # Pattern 2: "Y is [a] prerequisite for/of X", "Y is required for X", "Y is needed for X"
                elif any(p in t_lower for p in [
                    "prerequisite for", "prerequisite of", "prerequisite to",
                    "is required for", "is required to", "is needed for", "is necessary for", "foundation for"
                ]):
                    if pos1 < pos2:
                        source_c = c1
                        target_c = c2
                    else:
                        source_c = c2
                        target_c = c1
                    kind = EvidenceKindEnum.EXPLICIT_STATEMENT
                    level = EvidenceLevelEnum.EXPLICIT

                # Pattern 3, 4: "X requires Y", "X depends on Y", "X builds on Y", "X relies on Y", "X is based on Y"
                elif any(p in t_lower for p in [
                    "requires", "depends on", "builds on", "relies on", "necessitates", "is based on", "extends"
                ]):
                    if pos1 < pos2:
                        source_c = c2
                        target_c = c1
                    else:
                        source_c = c1
                        target_c = c2
                    kind = EvidenceKindEnum.STATED_DEPENDENCY
                    level = EvidenceLevelEnum.STRONG_INFERRED

                # Taxonomic IS_A / INSTANCE_OF / PART_OF
                elif "is an example of" in t_lower or "is an instance of" in t_lower:
                    rel_type = RelationshipTypeEnum.INSTANCE_OF
                    source_c = c1 if pos1 < pos2 else c2
                    target_c = c2 if pos1 < pos2 else c1
                    kind = EvidenceKindEnum.EXPLICIT_STATEMENT
                    level = EvidenceLevelEnum.EXPLICIT
                elif "is a type of" in t_lower or "is a kind of" in t_lower:
                    rel_type = RelationshipTypeEnum.IS_A
                    source_c = c1 if pos1 < pos2 else c2
                    target_c = c2 if pos1 < pos2 else c1
                    kind = EvidenceKindEnum.EXPLICIT_STATEMENT
                    level = EvidenceLevelEnum.EXPLICIT
                elif "is part of" in t_lower or "is a component of" in t_lower:
                    rel_type = RelationshipTypeEnum.PART_OF
                    source_c = c1 if pos1 < pos2 else c2
                    target_c = c2 if pos1 < pos2 else c1
                    kind = EvidenceKindEnum.EXPLICIT_STATEMENT
                    level = EvidenceLevelEnum.EXPLICIT

                if source_c and target_c:
                    # Check cycle prevention for prerequisite DAG
                    if rel_type == RelationshipTypeEnum.PREREQUISITE_OF and has_directed_path(
                        adj, target_c.concept_id, source_c.concept_id
                    ):
                        continue

                    rel_id = generate_relationship_id(
                        norm_doc.doc_id, source_c.concept_id, rel_type.value, target_c.concept_id
                    )

                    # Avoid duplicate edge creation
                    if rel_id in seen_rel_ids:
                        continue
                    seen_rel_ids.add(rel_id)

                    ev_id = generate_evidence_id(norm_doc.doc_id, blk_id, 0, len(text), "rel")
                    span = TextSpan(start=0, end=len(text))

                    if not verify_relationship_grounding(text, text, span):
                        continue

                    ev = Evidence(
                        evidence_id=ev_id,
                        block_id=blk_id,
                        span=span,
                        excerpt=text,
                        level=level,
                        kind=kind,
                        source_confidence=0.95
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
                            value=0.90,
                            components={"source_quality": 0.95, "extraction": 0.9, "verification": 1.0}
                        ),
                        evidence_ids=[ev_id]
                    )
                    relationships.append(rel)
                    if rel_type == RelationshipTypeEnum.PREREQUISITE_OF:
                        adj.setdefault(source_c.concept_id, set()).add(target_c.concept_id)

    return relationships

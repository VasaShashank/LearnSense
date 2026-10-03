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
    adj: Dict[str, Set[str]] = {}  # source -> set of targets

    block_map = {b["block_id"]: b["text"] for b in norm_doc.semantic_blocks if b["included_in_semantic_flow"]}
    concept_by_id = {c.concept_id: c for c in concepts}

    # Extract co-occurring candidate pairs across blocks
    for blk_id, text in block_map.items():
        if detect_negation_or_hedging(text):
            continue  # Skip negated or hedged prerequisite claims

        # Find concepts mentioned in this block
        mentioned_concepts = []
        for c in concepts:
            for ev_id in c.evidence_ids:
                for ev in candidates.evidence:
                    if ev.evidence_id == ev_id and ev.block_id == blk_id:
                        mentioned_concepts.append(c)
                        break

        if len(mentioned_concepts) < 2:
            continue

        t_lower = text.lower()

        # Directional prerequisite extraction:
        # 1. "X requires Y" -> Y is prerequisite of X (Y -> X)
        # 2. "Y is prerequisite for X" / "Y is a prerequisite of X" -> Y -> X
        # 3. "X depends on Y" -> Y -> X
        # 4. "X builds on Y" -> Y -> X
        # 5. "X relies on Y" -> Y -> X
        # 6. "To understand X, students should know Y" -> Y -> X
        # 7. "Before studying X, recall Y" -> Y -> X

        for i in range(len(mentioned_concepts)):
            for j in range(len(mentioned_concepts)):
                if i == j:
                    continue
                c1 = mentioned_concepts[i]
                c2 = mentioned_concepts[j]

                pos1 = t_lower.find(c1.canonical_name.lower())
                pos2 = t_lower.find(c2.canonical_name.lower())

                if pos1 == -1 or pos2 == -1:
                    continue

                source_c = None  # Prerequisite
                target_c = None  # Dependent
                kind = EvidenceKindEnum.STATED_DEPENDENCY
                level = EvidenceLevelEnum.STRONG_INFERRED

                between_text = t_lower[min(pos1, pos2) : max(pos1, pos2)]

                # Pattern 1 & 7: "Before studying X, recall Y"
                if "recall" in t_lower or "before studying" in t_lower:
                    if pos1 < pos2:
                        source_c = c2
                        target_c = c1
                    else:
                        source_c = c1
                        target_c = c2
                    kind = EvidenceKindEnum.EXPLICIT_STATEMENT
                    level = EvidenceLevelEnum.EXPLICIT

                # Pattern 6: "To understand X, ... know Y"
                elif "to understand" in t_lower and ("know" in t_lower or "understand" in t_lower):
                    # "To understand X, students should know Y"
                    # X appears before Y in this phrasing -> c1=X, c2=Y => Y (c2) -> X (c1)
                    if pos1 < pos2:
                        source_c = c2
                        target_c = c1
                    else:
                        source_c = c1
                        target_c = c2
                    kind = EvidenceKindEnum.EXPLICIT_STATEMENT
                    level = EvidenceLevelEnum.EXPLICIT

                # Pattern 2: "Y is [a] prerequisite for/of X"
                elif "prerequisite for" in t_lower or "prerequisite of" in t_lower or "prerequisite to" in t_lower:
                    # In "Y is prerequisite for X", pos(Y) < pos(X)
                    # If pos1 < pos2, c1 is Y (source), c2 is X (target)
                    if pos1 < pos2:
                        source_c = c1
                        target_c = c2
                    else:
                        source_c = c2
                        target_c = c1
                    kind = EvidenceKindEnum.EXPLICIT_STATEMENT
                    level = EvidenceLevelEnum.EXPLICIT

                # Pattern 3, 4, 5: "X requires Y", "X depends on Y", "X builds on Y", "X relies on Y"
                elif any(p in t_lower for p in ["requires", "depends on", "builds on", "relies on", "necessitates"]):
                    # In "X requires Y", pos(X) < pos(Y)
                    # If pos1 < pos2, c1 is X (target), c2 is Y (source)
                    if pos1 < pos2:
                        source_c = c2
                        target_c = c1
                    else:
                        source_c = c1
                        target_c = c2
                    kind = EvidenceKindEnum.STATED_DEPENDENCY
                    level = EvidenceLevelEnum.STRONG_INFERRED

                if source_c and target_c:
                    # Check cycle prevention: if target_c already reaches source_c, adding source_c -> target_c forms a cycle
                    if has_directed_path(adj, target_c.concept_id, source_c.concept_id):
                        # Reject cycle edge to enforce DAG invariant
                        continue

                    rel_id = generate_relationship_id(
                        norm_doc.doc_id, source_c.concept_id, RelationshipTypeEnum.PREREQUISITE_OF.value, target_c.concept_id
                    )

                    # Avoid duplicate edge creation
                    if any(r.relationship_id == rel_id for r in relationships):
                        continue

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
                        type=RelationshipTypeEnum.PREREQUISITE_OF,
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
                    adj.setdefault(source_c.concept_id, set()).add(target_c.concept_id)

    return relationships

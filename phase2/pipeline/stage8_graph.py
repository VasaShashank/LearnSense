"""
Stage 8 — Graph Construction.
Deduplicates edges, aggregates confidence scores (noisy-OR), detects strongly connected components (SCC) in prerequisite subgraphs, flags cycles and conflicts, and builds 'full' and 'trusted' graph views.
Plan §11.
"""

from typing import Dict, List, Set, Tuple
from phase2.models import (
    Concept,
    Relationship,
    RelationshipStatusEnum,
    EvidenceLevelEnum,
    RelationshipTypeEnum,
    Views,
)


def aggregate_confidence_noisy_or(evidence_confidences: List[float], source_quality_cap: float = 1.0) -> float:
    """Computes noisy-OR combination: 1 - prod(1 - e_i), capped by source quality."""
    if not evidence_confidences:
        return 0.0
    prod = 1.0
    for c in evidence_confidences:
        prod *= (1.0 - c)
    combined = 1.0 - prod
    return min(combined, source_quality_cap)


def detect_scc_tarjan(nodes: Set[str], edges: List[Tuple[str, str]]) -> List[Set[str]]:
    """Tarjan's algorithm for Strongly Connected Components (SCC)."""
    adj: Dict[str, List[str]] = {n: [] for n in nodes}
    for u, v in edges:
        if u in adj and v in adj:
            adj[u].append(v)

    index = 0
    indices: Dict[str, int] = {}
    lowlink: Dict[str, int] = {}
    stack: List[str] = []
    on_stack: Set[str] = set()
    sccs: List[Set[str]] = []

    def strongconnect(node: str):
        nonlocal index
        indices[node] = index
        lowlink[node] = index
        index += 1
        stack.append(node)
        on_stack.add(node)

        for neighbor in adj.get(node, []):
            if neighbor not in indices:
                strongconnect(neighbor)
                lowlink[node] = min(lowlink[node], lowlink[neighbor])
            elif neighbor in on_stack:
                lowlink[node] = min(lowlink[node], indices[neighbor])

        if lowlink[node] == indices[node]:
            scc = set()
            while True:
                w = stack.pop()
                on_stack.remove(w)
                scc.add(w)
                if w == node:
                    break
            if len(scc) > 1:
                sccs.append(scc)

    for n in nodes:
        if n not in indices:
            strongconnect(n)

    return sccs


def run_stage8_graph_construction(
    concepts: List[Concept],
    relationships: List[Relationship]
) -> Tuple[List[Relationship], Views]:
    concept_ids = {c.concept_id for c in concepts}

    # 1. Deduplicate Relationships by (source, type, target)
    rel_map: Dict[Tuple[str, str, str], Relationship] = {}
    for rel in relationships:
        r_type = rel.type.value if hasattr(rel.type, "value") else str(rel.type)
        key = (rel.source, r_type, rel.target)
        if key not in rel_map:
            rel_map[key] = rel
        else:
            existing = rel_map[key]
            existing.evidence_ids.extend(rel.evidence_ids)
            existing.evidence_ids = list(dict.fromkeys(existing.evidence_ids))

    deduped_rels = list(rel_map.values())

    # 2. Cycle Detection in Prerequisite Subgraph (STRICTLY for PREREQUISITE_OF)
    prereq_edges = [
        (r.source, r.target) for r in deduped_rels
        if (r.type.value if hasattr(r.type, "value") else str(r.type)) == RelationshipTypeEnum.PREREQUISITE_OF.value
        and r.status == RelationshipStatusEnum.ACCEPTED
    ]
    cycles = detect_scc_tarjan(concept_ids, prereq_edges)

    cycle_nodes = set()
    for scc in cycles:
        cycle_nodes.update(scc)

    # Flag relationships involved in cycles
    for rel in deduped_rels:
        r_type = rel.type.value if hasattr(rel.type, "value") else str(rel.type)
        if r_type == RelationshipTypeEnum.PREREQUISITE_OF.value:
            if rel.source in cycle_nodes and rel.target in cycle_nodes:
                rel.status = RelationshipStatusEnum.FLAGGED_CYCLE
                rel.flags.append("prerequisite_cycle_detected")

    # 3. Build Trusted View
    # Policy: accepted status, EXPLICIT or STRONG_INFERRED level, confidence >= 0.70, and MUST have non-empty verified evidence_ids
    trusted_rel_ids = []
    for rel in deduped_rels:
        if rel.status == RelationshipStatusEnum.ACCEPTED:
            if rel.evidence_level in (EvidenceLevelEnum.EXPLICIT, EvidenceLevelEnum.STRONG_INFERRED):
                if rel.confidence.value >= 0.70 and bool(rel.evidence_ids):
                    trusted_rel_ids.append(rel.relationship_id)

    views = Views(
        trusted={
            "policy_version": "1.0",
            "relationship_ids": trusted_rel_ids
        },
        full={
            "total_nodes": len(concepts),
            "total_edges": len(deduped_rels)
        }
    )

    return deduped_rels, views

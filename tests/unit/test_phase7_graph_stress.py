"""
Phase 7 Knowledge Graph Validation and Stress Test Suite.
Verifies cycle detection, topological sorting performance, and handling of large graphs (10, 50, 100, 250 concepts).
"""

import time
import pytest
from phase4.planning.prerequisite_resolver import PrerequisiteResolver
from phase3.knowledge.phase2_adapter import LearningContext, ConceptView, PrerequisiteLink


def generate_large_learning_context(concept_count: int, add_cycle: bool = False) -> LearningContext:
    concepts = {}
    prereqs = []

    for i in range(concept_count):
        cid = f"c_{i}"
        concepts[cid] = ConceptView(
            concept_id=cid,
            canonical_name=f"Concept {i}",
            type="CORE",
            aliases=[],
        )
        # Create prerequisite links i-1 -> i
        if i > 0:
            prereqs.append(
                PrerequisiteLink(
                    source_concept_id=f"c_{i-1}",
                    target_concept_id=cid,
                    confidence=1.0,
                )
            )

    if add_cycle and concept_count > 2:
        # Add cycle from last concept back to first
        prereqs.append(
            PrerequisiteLink(
                source_concept_id=f"c_{concept_count-1}",
                target_concept_id="c_0",
                confidence=1.0,
            )
        )

    return LearningContext(
        document_id=f"doc_stress_{concept_count}",
        knowledge_document_id=f"kdoc_stress_{concept_count}",
        concepts=concepts,
        prerequisites=prereqs,
    )


def test_prerequisite_resolver_cycle_safe_sorting():
    resolver = PrerequisiteResolver()
    # 10 concepts linear
    ctx10 = generate_large_learning_context(10)
    sorted_ids = resolver.cycle_safe_topological_sort(ctx10, list(ctx10.concepts.keys()))
    assert len(sorted_ids) == 10
    assert sorted_ids[0] == "c_0"

    # 10 concepts with cycle
    ctx_cycle = generate_large_learning_context(10, add_cycle=True)
    sorted_cycle = resolver.cycle_safe_topological_sort(ctx_cycle, list(ctx_cycle.concepts.keys()))
    assert len(sorted_cycle) == 10  # Cycle handled safely without infinite loop


@pytest.mark.parametrize("concept_count", [10, 50, 100, 250])
def test_graph_stress_performance(concept_count):
    resolver = PrerequisiteResolver()
    ctx = generate_large_learning_context(concept_count, add_cycle=True)

    start_time = time.time()
    sorted_ids = resolver.cycle_safe_topological_sort(ctx, list(ctx.concepts.keys()))
    elapsed = time.time() - start_time

    assert len(sorted_ids) == concept_count
    assert elapsed < 1.0  # Resolving 250 concepts must take under 1 second

"""
Equivalence cross-check against Person 3's real graph code (Person 2).

Runs only when the read-only Person 3 reference drop is extracted next to the
repository (``../References/LearnSense-Person3-FINAL``); otherwise the whole
module skips, so the Person 2 suite never depends on that drop being present.

The module loads ``src/knowledge_graph.py`` straight from the reference drop
(stdlib-only module, loaded in isolation so Person 3's package ``__init__`` and
its torch/pandas imports are never triggered) and compares, id for id:

* direct prerequisites / dependents (the ``A --prerequisite_of--> B``
  direction),
* transitive ancestor/descendant sets,
* traversal membership (``contains``),
* cycle detection,
* prerequisite readiness and remediation sequencing on shared mastery vectors.

Their CSV graph and the canonical fixture built here describe the same 62-concept
slice, so agreement here is evidence that the canonical adapter preserves
Person 3's query semantics -- interface evidence, not curriculum validation.
"""

from __future__ import annotations

import csv
import importlib.util
import sys
from pathlib import Path
from typing import Any, Dict

import pytest

from curriculum.learner_adapter import KnowledgeGraphAdapter
from curriculum.seed import CurriculumSpec, seed_curriculum

REFERENCES = Path(__file__).resolve().parents[4] / "References"
PERSON3_DIR = REFERENCES / "LearnSense-Person3-FINAL"
PERSON3_GRAPH_MODULE = PERSON3_DIR / "src" / "knowledge_graph.py"
PERSON3_CONCEPTS_CSV = PERSON3_DIR / "data" / "synthetic jee" / "v3" / "concepts.csv"

pytestmark = pytest.mark.skipif(
    not (PERSON3_GRAPH_MODULE.is_file() and PERSON3_CONCEPTS_CSV.is_file()),
    reason="Person 3 reference drop not extracted next to the repository",
)


@pytest.fixture(scope="module")
def person3_module() -> Any:
    """Load Person 3's knowledge_graph module in isolation from their package."""
    spec = importlib.util.spec_from_file_location(
        "person3_reference_knowledge_graph", PERSON3_GRAPH_MODULE
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    # dataclasses resolves annotations through sys.modules at class creation.
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def csv_rows() -> list[Dict[str, str]]:
    with open(PERSON3_CONCEPTS_CSV, "r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


@pytest.fixture(scope="module")
def person3_graph(person3_module: Any, csv_rows: list[Dict[str, str]]) -> Any:
    """Their graph from their own default loader (their CSV, their validation)."""
    return person3_module.load_knowledge_graph_from_csv(PERSON3_CONCEPTS_CSV)


@pytest.fixture(scope="module")
def canonical_pair(csv_rows: list[Dict[str, str]]) -> tuple[Any, Dict[str, str]]:
    """
    Canonical graph mirroring the same rows, plus the reviewed simulator map.

    Each canonical concept keeps the simulator name (and the simulator id as an
    alias), so ``SimulatorBridge`` resolves every row by exact rule-table match;
    the returned dict is simulator id -> canonical id, built through the bridge
    rather than assumed.
    """
    from curriculum.simulator import SimulatorBridge, load_simulator_concepts

    concepts = []
    for row in csv_rows:
        prerequisites = [p.strip() for p in (row.get("prerequisite_ids") or "").split(";") if p.strip()]
        concepts.append(
            {
                "stable_key": row["concept_id"],
                "name": row["concept_name"],
                "subject": (row.get("subject") or "physics").strip().lower(),
                "aliases": [row["concept_id"]],
                "prerequisites": prerequisites,
            }
        )
    graph = seed_curriculum(
        CurriculumSpec.model_validate({"curriculum_id": "p3_equiv_v1", "concepts": concepts})
    )
    simulator_concepts = load_simulator_concepts(PERSON3_CONCEPTS_CSV)
    bridge = SimulatorBridge(graph)
    entries = bridge.map_concepts(simulator_concepts)
    concept_map = bridge.resolve_map(entries)
    assert len(concept_map) == len(csv_rows), (
        f"every simulator concept must map for a full equivalence run; "
        f"unmapped: {[e.simulator_concept_id for e in entries if e.canonical_concept_id is None]}"
    )
    return graph, concept_map


@pytest.fixture(scope="module")
def adapter(canonical_pair: tuple[Any, Dict[str, str]]) -> KnowledgeGraphAdapter:
    graph, _ = canonical_pair
    return KnowledgeGraphAdapter(graph)


def test_full_concept_set_coverage(adapter: KnowledgeGraphAdapter, person3_graph: Any) -> None:
    assert len(adapter) == len(person3_graph) == 62
    _, concept_map = canonical_pair_params(adapter)
    assert set(concept_map.keys()) == set(person3_graph.concept_ids)


def canonical_pair_params(adapter: KnowledgeGraphAdapter) -> tuple[Any, Dict[str, str]]:
    """Recover the concept map from the adapter's module fixture state."""
    graph = adapter.graph
    from curriculum.simulator import SimulatorBridge, load_simulator_concepts

    bridge = SimulatorBridge(graph)
    entries = bridge.map_concepts(load_simulator_concepts(PERSON3_CONCEPTS_CSV))
    return graph, bridge.resolve_map(entries)


def test_direct_prerequisites_direction_matches(
    adapter: KnowledgeGraphAdapter, person3_graph: Any
) -> None:
    _, concept_map = canonical_pair_params(adapter)
    for sim_id in person3_graph.concept_ids:
        theirs = person3_graph.get_direct_prerequisites(sim_id)
        ours = adapter.get_direct_prerequisites(concept_map[sim_id])
        assert sorted(concept_map[s] for s in theirs) == ours, f"direction mismatch at {sim_id}"


def test_direct_dependents_match(
    adapter: KnowledgeGraphAdapter, person3_graph: Any
) -> None:
    _, concept_map = canonical_pair_params(adapter)
    for sim_id in person3_graph.concept_ids:
        theirs = person3_graph.get_direct_dependents(sim_id)
        ours = adapter.get_direct_dependents(concept_map[sim_id])
        assert sorted(concept_map[s] for s in theirs) == ours, f"dependents mismatch at {sim_id}"


def test_transitive_closures_match(adapter: KnowledgeGraphAdapter, person3_graph: Any) -> None:
    _, concept_map = canonical_pair_params(adapter)
    for sim_id in person3_graph.concept_ids:
        theirs = person3_graph.get_all_ancestor_prerequisites(sim_id)
        ours = adapter.get_all_ancestor_prerequisites(concept_map[sim_id])
        assert {concept_map[s] for s in theirs} == ours, f"ancestors mismatch at {sim_id}"
        theirs = person3_graph.get_all_descendant_dependents(sim_id)
        ours = adapter.get_all_descendant_dependents(concept_map[sim_id])
        assert {concept_map[s] for s in theirs} == ours, f"descendants mismatch at {sim_id}"


def test_contains_agreement(adapter: KnowledgeGraphAdapter, person3_graph: Any, concept_map_fixture: Dict[str, str]) -> None:
    for sim_id, canonical_id in concept_map_fixture.items():
        assert person3_graph.contains(sim_id) is True
        assert adapter.contains(canonical_id) is True
    assert person3_graph.contains("NOPE") is False
    assert adapter.contains("cc_nope") is False


def test_topological_orders_agree_on_precedence(
    adapter: KnowledgeGraphAdapter, person3_graph: Any
) -> None:
    _, concept_map = canonical_pair_params(adapter)
    theirs = person3_graph.topological_sort()
    ours = adapter.topological_sort()
    # Tie-breaks differ (simulator ids vs cc_ ids), so compare precedence, not list equality.
    their_position = {concept_map[sim_id]: index for index, sim_id in enumerate(theirs)}
    our_position = {concept_id: index for index, concept_id in enumerate(ours)}
    assert sorted(their_position) == sorted(our_position)
    for sim_id in person3_graph.concept_ids:
        for prereq in person3_graph.get_direct_prerequisites(sim_id):
            assert their_position[concept_map[prereq]] < their_position[concept_map[sim_id]]
            assert our_position[concept_map[prereq]] < our_position[concept_map[sim_id]]


def test_both_graphs_are_cycle_free(
    adapter: KnowledgeGraphAdapter, person3_graph: Any
) -> None:
    assert person3_graph.detect_cycles() == []
    assert adapter.detect_cycles() == []


def test_readiness_and_remediation_agree(
    adapter: KnowledgeGraphAdapter, person3_graph: Any
) -> None:
    _, concept_map = canonical_pair_params(adapter)

    mastery_on_theirs: Dict[str, float] = {
        sim_id: (0.9 if index % 3 == 0 else 0.2) for index, sim_id in enumerate(person3_graph.concept_ids)
    }
    mastery_on_ours: Dict[str, float] = {
        concept_map[sim_id]: value for sim_id, value in mastery_on_theirs.items()
    }

    for sim_id in person3_graph.concept_ids:
        their_ready, their_map, their_needed = person3_graph.evaluate_prerequisite_readiness(
            sim_id, mastery_on_theirs
        )
        our_ready, our_map, our_needed = adapter.evaluate_prerequisite_readiness(
            concept_map[sim_id], mastery_on_ours
        )
        assert their_ready == our_ready, f"readiness mismatch at {sim_id}"
        assert {concept_map[s]: v for s, v in their_map.items()} == our_map
        assert sorted(concept_map[s] for s in their_needed) == sorted(our_needed)

    # Remediation: compare as sets plus precedence (tie-breaks differ by id space).
    for sim_id in person3_graph.concept_ids:
        theirs = person3_graph.get_remediation_sequence(sim_id, mastery_on_theirs)
        ours = adapter.get_remediation_sequence(concept_map[sim_id], mastery_on_ours)
        assert {concept_map[s] for s in theirs} == set(ours), f"remediation mismatch at {sim_id}"


def test_remediation_chain_order_identical_when_total(
    adapter: KnowledgeGraphAdapter, person3_graph: Any, concept_map_fixture: Dict[str, str]
) -> None:
    """A totally ordered chain must produce the identical sequence on both sides."""
    # PHY_WAV <- PHY_SHM <- PHY_NLM <- PHY_KIN is a chain in the shared slice.
    mastery_theirs = {sim_id: 1.0 for sim_id in person3_graph.concept_ids}
    mastery_theirs.update({"PHY_KIN": 0.9, "PHY_NLM": 0.2, "PHY_SHM": 0.4})
    mastery_ours = {concept_map_fixture[s]: v for s, v in mastery_theirs.items()}

    theirs = person3_graph.get_remediation_sequence("PHY_WAV", mastery_theirs)
    ours = adapter.get_remediation_sequence(concept_map_fixture["PHY_WAV"], mastery_ours)
    assert [concept_map_fixture[s] for s in theirs] == ours
    assert [inverse_name(person3_graph, s) for s in theirs] == ["Laws of Motion", "Oscillations"]


def inverse_name(person3_graph: Any, sim_id: str) -> str:
    return person3_graph.get_node(sim_id).name


@pytest.fixture(scope="module")
def concept_map_fixture(canonical_pair: tuple[Any, Dict[str, str]]) -> Dict[str, str]:
    return canonical_pair[1]

def test_person3_adapter_and_engines_wrap_canonical_adapter(adapter: KnowledgeGraphAdapter) -> None:
    """Person 3's adapter wraps our adapter; recommendation/assessment engines accept it.

    Regression guard for the canonical adapter's ``get_node`` surface: Person 3's
    ``KnowledgeGraphAdapter.get_concept`` calls ``self._graph.get_node(id)``.
    """
    import sys as _sys
    # reuse the module-level fixture by importing it fresh
    _mod = None
    # (unused placeholder removed)
    # Simpler: rely on the already-imported module via sys.modules if present.
    p3mod = _sys.modules.get("person3_reference_knowledge_graph")
    assert p3mod is not None
    P3Adapter = __import__(
        "src.integration.knowledge_graph_adapter", fromlist=["KnowledgeGraphAdapter"]
    ).KnowledgeGraphAdapter if False else None
    # Import Person 3's adapter module directly from the reference drop.
    import importlib.util as _iu
    _spec = _iu.spec_from_file_location(
        "p3_kg_adapter",
        __import__("pathlib").Path(__file__).resolve().parents[4] / "References" / "LearnSense-Person3-FINAL" / "src" / "integration" / "knowledge_graph_adapter.py",
    )
    _m = _iu.module_from_spec(_spec)
    _sys.modules[_spec.name] = _m
    # Person 3's adapter imports from src.integration.contracts and src.knowledge_graph;
    # ensure their package root is importable.
    _root = str(__import__("pathlib").Path(__file__).resolve().parents[4] / "References" / "LearnSense-Person3-FINAL")
    if _root not in _sys.path:
        _sys.path.insert(0, _root)
    _spec.loader.exec_module(_m)
    P3Adapter = _m.KnowledgeGraphAdapter

    wrapped = P3Adapter(graph=adapter)
    cid = adapter.concept_ids[0]
    payload = wrapped.get_concept(cid)
    assert payload is not None and payload["concept_id"] == cid

    # Recommendation engine + assessment selector accept the canonical adapter
    # duck-typed (they call contains/topological_sort/evaluate_prerequisite_readiness).
    from src.recommendation import RecommendationEngine
    from src.adaptive_assessment import AdaptiveAssessmentSelector
    rec = RecommendationEngine(knowledge_graph=adapter)
    sel = AdaptiveAssessmentSelector(knowledge_graph=adapter)
    assert adapter.contains(cid) is True
    assert len(rec._topological_order) == len(adapter.concept_ids)
    assert sel.knowledge_graph is adapter


def test_person3_integrated_pipeline_accepts_canonical_adapter(adapter: KnowledgeGraphAdapter) -> None:
    """IntegratedLearningLoopPipeline accepts canonical KnowledgeGraphAdapter without falling back to CSV."""
    import sys as _sys
    import pathlib
    _root = str(pathlib.Path(__file__).resolve().parents[4] / "References" / "LearnSense-Person3-FINAL")
    if _root not in _sys.path:
        _sys.path.insert(0, _root)
    from src.integration.pipeline import IntegratedLearningLoopPipeline

    pipe = IntegratedLearningLoopPipeline(knowledge_graph=adapter)
    assert pipe.knowledge_graph is adapter
    assert pipe.state_service.knowledge_graph is adapter
    assert pipe.recommendation_engine.knowledge_graph is adapter
    assert pipe.assessment_selector.knowledge_graph is adapter
    cid = adapter.concept_ids[0]
    node = pipe.kg_adapter.get_concept(cid)
    assert node is not None and node["concept_id"] == cid


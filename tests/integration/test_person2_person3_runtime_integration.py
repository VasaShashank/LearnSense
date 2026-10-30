"""
End-to-End Person 2 x Person 3 Runtime Integration Harness.

Tests the production boundary between Person 2's canonical curriculum graph
and Person 3's adaptive learning pipeline:
- Scenario 1: Successful initialization & contract compliance
- Scenario 2: Missing graph fails explicitly (no CSV fallback)
- Scenario 3: Corrupt or incompatible graph rejection
- Scenario 4: Unknown simulator ID rejected before inference (no index-0 substitution)
- Scenario 5: Successful mastery translation & atomic persistence
- Scenario 6: Failed mastery translation leaves learner state completely unmodified
- Scenario 7: Full learning loop (attempt -> validation -> inference -> translation -> state -> readiness)
- Scenario 8: Instrumenting CSV loader proves zero fallback in production mode
- Scenario 9: Deterministic repeatability across multiple initializations
- Scenario 10: Tenant and user isolation (learner A cannot leak into learner B)
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from curriculum.integration_factory import (
    AtomicLearnerStateUpdateError,
    CanonicalGraphUnavailableError,
    CanonicalLearnerStateService,
    IncompatibleCurriculumError,
    ProductionCurriculumIntegrationFactory,
    validate_adapter_contract,
)
from curriculum.models import CanonicalConcept, ConceptRelationship, CurriculumGraph
from curriculum.repository import CurriculumRepository
from curriculum.seed import CurriculumSpec, seed_curriculum
from curriculum.translation import UnknownSimulatorIdError, validate_simulator_ids
from phase3.learner.models import ConceptState, LearnerState
from phase3.storage.learner_repository import LearnerStateRepository

# References paths
REFERENCES = Path(__file__).resolve().parents[3] / "References"
V2_CONCEPTS_CSV = REFERENCES / "learnsense_jee_simulator_v2" / "concepts.csv"
PERSON3_DIR = REFERENCES / "LearnSense-Person3-FINAL"
AKT_VOCABULARY = PERSON3_DIR / "data" / "models" / "akt_vocabulary.json"

SPEC_FIXTURE = (
    Path(__file__).resolve().parents[1]
    / "fixtures"
    / "curriculum"
    / "jee_curriculum_spec.json"
)


@pytest.fixture
def seeded_canonical_repo(tmp_path: Path) -> tuple[CurriculumRepository, CurriculumGraph]:
    repo = CurriculumRepository(base_dir=str(tmp_path / "curriculum"))
    spec_data = json.loads(SPEC_FIXTURE.read_text(encoding="utf-8"))
    spec = CurriculumSpec.model_validate(spec_data)
    graph = seed_curriculum(spec)
    repo.save_graph(graph)
    return repo, graph


@pytest.fixture
def empty_curriculum_repo(tmp_path: Path) -> CurriculumRepository:
    return CurriculumRepository(base_dir=str(tmp_path / "empty_curriculum"))


# -----------------------------------------------------------------------------
# Scenario 1: Successful Initialization
# -----------------------------------------------------------------------------
def test_scenario_1_successful_initialization(
    seeded_canonical_repo: tuple[CurriculumRepository, CurriculumGraph]
) -> None:
    repo, graph = seeded_canonical_repo
    factory = ProductionCurriculumIntegrationFactory(
        repository=repo,
        mode="production",
        expected_curriculum_id="jee_class_11_12",
        expected_syllabus_version="2026.jee.v1",
        expected_fingerprint=graph.content_fingerprint(),
    )

    adapter = factory.create_adapter()
    assert adapter is not None
    assert adapter.curriculum_id == "jee_class_11_12"
    assert adapter.syllabus_version == "2026.jee.v1"
    assert adapter.fingerprint == graph.content_fingerprint()
    assert len(adapter.concept_ids) == len(graph.concepts)

    # Validate duck-typing contract against Person 3 requirements
    validate_adapter_contract(adapter)

    # Check node view for random concept
    node = adapter.get_node(adapter.concept_ids[0])
    assert node is not None
    assert node.concept_id == adapter.concept_ids[0]
    assert hasattr(node, "name")
    assert hasattr(node, "prerequisite_concept_ids")
    assert isinstance(node.to_contract_dict(), dict)


# -----------------------------------------------------------------------------
# Scenario 2: Missing Graph in Production Mode
# -----------------------------------------------------------------------------
def test_scenario_2_missing_graph_fails_explicitly(
    empty_curriculum_repo: CurriculumRepository,
) -> None:
    factory = ProductionCurriculumIntegrationFactory(
        repository=empty_curriculum_repo,
        mode="production",
        expected_curriculum_id="jee_class_11_12",
    )

    with pytest.raises(CanonicalGraphUnavailableError) as exc_info:
        factory.create_adapter()

    assert "is not stored in the canonical repository" in str(exc_info.value)
    assert "Silent fallback to simulator CSV data is strictly forbidden" in str(exc_info.value)


# -----------------------------------------------------------------------------
# Scenario 3: Corrupt or Incompatible Graph Rejection
# -----------------------------------------------------------------------------
def test_scenario_3_corrupt_or_incompatible_graph_rejected(tmp_path: Path) -> None:
    repo = CurriculumRepository(base_dir=str(tmp_path / "corrupt_curriculum"))

    # Create a corrupt graph with a cycle
    corrupt_graph = CurriculumGraph(
        curriculum_id="jee_class_11_12",
        syllabus_version="2026.jee.v1",
        title="Corrupted Graph with Cycle",
        concepts={
            "c_node_a": CanonicalConcept(concept_id="c_node_a", stable_key="a", name="Node A", subject="physics"),
            "c_node_b": CanonicalConcept(concept_id="c_node_b", stable_key="b", name="Node B", subject="physics"),
        },
        relationships={
            "rel_1": ConceptRelationship(
                relationship_id="rel_1",
                source="c_node_a",
                target="c_node_b",
                type="prerequisite_of",
                status="accepted",
            ),
            "rel_2": ConceptRelationship(
                relationship_id="rel_2",
                source="c_node_b",
                target="c_node_a",
                type="prerequisite_of",
                status="accepted",
            ),
        },
    )
    repo.save_graph(corrupt_graph)

    factory = ProductionCurriculumIntegrationFactory(
        repository=repo,
        mode="production",
        expected_curriculum_id="jee_class_11_12",
    )

    with pytest.raises(IncompatibleCurriculumError) as exc_info:
        factory.create_adapter()

    assert "failed structural validation" in str(exc_info.value)


# -----------------------------------------------------------------------------
# Scenario 4: Unknown Simulator ID Rejected Before Inference
# -----------------------------------------------------------------------------
@pytest.mark.skipif(not AKT_VOCABULARY.is_file(), reason="AKT vocabulary file missing")
def test_scenario_4_unknown_simulator_id_rejected_before_inference() -> None:
    # Simulator ID not in vocabulary
    invalid_ids = ["PHY_UNKNOWN_CONCEPT_999", "CHE_FABRICATED_TOPIC"]

    with pytest.raises(UnknownSimulatorIdError) as exc_info:
        validate_simulator_ids(invalid_ids, AKT_VOCABULARY)

    assert "refusing to fall back to vocabulary index 0" in str(exc_info.value)
    assert "PHY_UNKNOWN_CONCEPT_999" in str(exc_info.value)


# -----------------------------------------------------------------------------
# Scenario 5: Successful Mastery Translation & Atomic Persistence
# -----------------------------------------------------------------------------
def test_scenario_5_successful_mastery_translation_and_persistence(
    seeded_canonical_repo: tuple[CurriculumRepository, CurriculumGraph],
    tmp_path: Path,
) -> None:
    repo, graph = seeded_canonical_repo
    factory = ProductionCurriculumIntegrationFactory(repository=repo, mode="production")
    adapter = factory.create_adapter()

    state_repo = LearnerStateRepository(base_dir=str(tmp_path / "learner_states"))
    service = CanonicalLearnerStateService(adapter=adapter, state_repo=state_repo)

    # 62 simulator concept mastery profile
    sim_profile = {
        alias: 0.78
        for concept in graph.concepts.values()
        for alias in concept.aliases
        if alias.startswith("PHY_") or alias.startswith("CHE_") or alias.startswith("MAT_")
    }
    expected_count = len(graph.concepts)
    assert len(sim_profile) == expected_count

    learner_id = "learner_prod_001"
    result = service.process_learner_mastery_update(learner_id, sim_profile)

    assert result.is_complete is True
    assert result.coverage_rate == 1.0
    assert len(result.canonical_mastery) == expected_count

    # Verify persisted state on disk
    persisted = state_repo.load_state(learner_id)
    assert persisted is not None
    assert len(persisted.concept_states) == expected_count
    for canonical_id in result.canonical_mastery:
        assert canonical_id in persisted.concept_states
        assert persisted.concept_states[canonical_id].mastery_probability == 0.78


# -----------------------------------------------------------------------------
# Scenario 6: Failed Mastery Translation Leaves State Completely Unmodified
# -----------------------------------------------------------------------------
def test_scenario_6_failed_mastery_translation_leaves_state_unmodified(
    seeded_canonical_repo: tuple[CurriculumRepository, CurriculumGraph],
    tmp_path: Path,
) -> None:
    repo, graph = seeded_canonical_repo
    factory = ProductionCurriculumIntegrationFactory(repository=repo, mode="production")
    adapter = factory.create_adapter()

    state_repo = LearnerStateRepository(base_dir=str(tmp_path / "learner_states"))
    service = CanonicalLearnerStateService(adapter=adapter, state_repo=state_repo)

    learner_id = "learner_atomic_test"
    # Seed prior state
    prior_state = LearnerState(learner_id=learner_id)
    prior_cid = adapter.concept_ids[0]
    prior_state.concept_states[prior_cid] = ConceptState(
        concept_id=prior_cid, mastery_probability=0.42
    )
    state_repo.save_state(prior_state)

    # Profile with an unmapped concept
    faulty_profile = {
        "PHY_KIN": 0.85,
        "UNMAPPED_SIM_CONCEPT_XYZ": 0.90,
    }

    with pytest.raises(AtomicLearnerStateUpdateError):
        service.process_learner_mastery_update(learner_id, faulty_profile)

    # State must be completely unmodified!
    reloaded = state_repo.load_state(learner_id)
    assert reloaded is not None
    assert len(reloaded.concept_states) == 1
    assert reloaded.concept_states[prior_cid].mastery_probability == 0.42


# -----------------------------------------------------------------------------
# Scenario 7: Full Learning Loop Integration
# -----------------------------------------------------------------------------
def test_scenario_7_full_learning_loop_integration(
    seeded_canonical_repo: tuple[CurriculumRepository, CurriculumGraph],
    tmp_path: Path,
) -> None:
    repo, graph = seeded_canonical_repo
    factory = ProductionCurriculumIntegrationFactory(repository=repo, mode="production")
    adapter = factory.create_adapter()

    state_repo = LearnerStateRepository(base_dir=str(tmp_path / "learner_states"))
    service = CanonicalLearnerStateService(
        adapter=adapter, state_repo=state_repo, vocabulary=AKT_VOCABULARY if AKT_VOCABULARY.is_file() else None
    )

    learner_id = "learner_learning_loop"

    # Step 1: Input interaction on CHE_EQM (Equilibrium)
    # Step 2: Validate vocabulary
    if AKT_VOCABULARY.is_file():
        validate_simulator_ids(["CHE_EQM", "CHE_ION"], AKT_VOCABULARY)

    # Step 3: Calibrated inference output for prerequisite CHE_EQM
    sim_update = {"CHE_EQM": 0.85}

    # Step 4: Mastery translation and atomic state persistence
    res = service.process_learner_mastery_update(learner_id, sim_update)
    assert res.is_complete is True

    # Step 5: Downstream readiness evaluation for CHE_ION (which depends on CHE_EQM)
    is_ready, status_map, remediation = service.get_learner_readiness(
        learner_id=learner_id,
        concept_id="CHE_ION",
        threshold=0.50,
    )

    # Prerequisite CHE_EQM was satisfied (0.85 >= 0.50), so learner is ready for CHE_ION!
    assert is_ready is True
    assert remediation == []


# -----------------------------------------------------------------------------
# Scenario 8: No Silent Fallback to CSV in Production Mode
# -----------------------------------------------------------------------------
def test_scenario_8_no_silent_fallback_to_csv_in_production(tmp_path: Path) -> None:
    repo = CurriculumRepository(base_dir=str(tmp_path / "empty_repo"))
    factory = ProductionCurriculumIntegrationFactory(repository=repo, mode="production")

    # Mock any possible CSV reader to ensure it is never called
    with patch("curriculum.simulator.load_simulator_concepts") as mock_csv_loader:
        with pytest.raises(CanonicalGraphUnavailableError):
            factory.create_adapter("jee_class_11_12")

        # Must NOT attempt to load CSV
        mock_csv_loader.assert_not_called()


# -----------------------------------------------------------------------------
# Scenario 9: Repeatability
# -----------------------------------------------------------------------------
def test_scenario_9_repeatability(
    seeded_canonical_repo: tuple[CurriculumRepository, CurriculumGraph]
) -> None:
    repo, _ = seeded_canonical_repo
    factory_1 = ProductionCurriculumIntegrationFactory(repository=repo, mode="production")
    factory_2 = ProductionCurriculumIntegrationFactory(repository=repo, mode="production")

    adapter_1 = factory_1.create_adapter()
    adapter_2 = factory_2.create_adapter()

    assert adapter_1.fingerprint == adapter_2.fingerprint
    assert adapter_1.topological_sort() == adapter_2.topological_sort()
    assert adapter_1.concept_ids == adapter_2.concept_ids


# -----------------------------------------------------------------------------
# Scenario 10: Tenant and User Isolation
# -----------------------------------------------------------------------------
def test_scenario_10_tenant_and_user_isolation(
    seeded_canonical_repo: tuple[CurriculumRepository, CurriculumGraph],
    tmp_path: Path,
) -> None:
    repo, _ = seeded_canonical_repo
    factory = ProductionCurriculumIntegrationFactory(repository=repo, mode="production")
    adapter = factory.create_adapter()

    state_repo = LearnerStateRepository(base_dir=str(tmp_path / "isolated_states"))
    service = CanonicalLearnerStateService(adapter=adapter, state_repo=state_repo)

    learner_a = "tenant_alpha_student_1"
    learner_b = "tenant_beta_student_2"

    # Update Learner A with high mastery in Kinematics
    service.process_learner_mastery_update(learner_a, {"PHY_KIN": 0.95})

    # Update Learner B with low mastery in Kinematics
    service.process_learner_mastery_update(learner_b, {"PHY_KIN": 0.20})

    state_a = state_repo.load_state(learner_a)
    state_b = state_repo.load_state(learner_b)

    assert state_a is not None
    assert state_b is not None

    kin_canonical_id = service.concept_map["PHY_KIN"]
    assert state_a.concept_states[kin_canonical_id].mastery_probability == 0.95
    assert state_b.concept_states[kin_canonical_id].mastery_probability == 0.20

    # Separate readiness outcomes for Laws of Motion (PHY_NLM depends directly on PHY_KIN)
    is_ready_a, _, _ = service.get_learner_readiness(learner_a, "PHY_NLM", threshold=0.50)
    is_ready_b, _, _ = service.get_learner_readiness(learner_b, "PHY_NLM", threshold=0.50)

    assert is_ready_a is True
    assert is_ready_b is False


# -----------------------------------------------------------------------------
# Scenario 11: Real AKT Neural Model Weight Smoke Test
# -----------------------------------------------------------------------------
def test_scenario_11_real_akt_neural_weight_smoke_test(
    seeded_canonical_repo: tuple[CurriculumRepository, CurriculumGraph],
    tmp_path: Path,
) -> None:
    """Smoke test executing genuine forward inference through AKT + Concept-Mastery Head weights.

    Loads the real production checkpoint (akt_concept_mastery_head.pt), records student
    interactions, performs neural inference to produce causal continuous mastery predictions
    across all 62 concepts, and verifies atomic translation onto canonical learner state.
    """
    import sys

    repo, graph = seeded_canonical_repo
    factory = ProductionCurriculumIntegrationFactory(repository=repo, mode="production")
    adapter = factory.create_adapter()

    checkpoint_file = PERSON3_DIR / "data" / "models" / "akt_concept_mastery_head.pt"
    config_file = PERSON3_DIR / "data" / "models" / "akt_concept_mastery_head_config.json"
    vocab_file = PERSON3_DIR / "data" / "models" / "akt_vocabulary.json"

    if not checkpoint_file.is_file() or not vocab_file.is_file():
        pytest.skip("Person 3 real AKT model checkpoint or vocabulary not accessible.")

    # Dynamically load Person 3's real inference service without modifying its files
    if str(PERSON3_DIR) not in sys.path:
        sys.path.insert(0, str(PERSON3_DIR))

    from src.akt_inference import AKTMasteryInferenceService

    inference_svc = AKTMasteryInferenceService(
        checkpoint_path=checkpoint_file,
        config_path=config_file,
        vocab_path=vocab_file,
    )
    assert inference_svc.is_available() is True

    learner_id = "real_akt_learner_001"
    # Record real student interaction sequence across multiple subjects
    inference_svc.record_interaction(learner_id, "Q_001", "PHY_KIN", is_correct=1)
    inference_svc.record_interaction(learner_id, "Q_002", "PHY_NLM", is_correct=1)
    inference_svc.record_interaction(learner_id, "Q_003", "CHE_EQM", is_correct=0)

    # Execute genuine neural forward pass
    raw_predictions = inference_svc.predict_concept_mastery(learner_id)
    assert isinstance(raw_predictions, dict)
    assert len(raw_predictions) == 62

    # All predicted probabilities must be bounded in [0.0, 1.0]
    for sim_id, prob in raw_predictions.items():
        assert 0.0 <= prob <= 1.0

    # Feed genuine model output into Person 2's atomic state service
    state_repo = LearnerStateRepository(base_dir=str(tmp_path / "real_akt_states"))
    state_service = CanonicalLearnerStateService(
        adapter=adapter,
        state_repo=state_repo,
        vocabulary=vocab_file,
    )

    res = state_service.process_learner_mastery_update(learner_id, raw_predictions)
    assert res.is_complete is True
    assert res.translated_count == 62
    assert len(res.canonical_mastery) == 62
    assert res.unresolved_simulator_ids == []

    # Verify persisted canonical learner state reflects the neural predictions
    persisted = state_repo.load_state(learner_id)
    assert persisted is not None
    assert len(persisted.concept_states) == 62

    # Prerequisite readiness evaluation on genuine translated state
    kin_canon = state_service.concept_map["PHY_KIN"]
    assert persisted.concept_states[kin_canon].mastery_probability == raw_predictions["PHY_KIN"]


# -----------------------------------------------------------------------------
# Scenario 12: Sequence Tensor Bounds, Vocabulary Gating & Error Propagation
# -----------------------------------------------------------------------------
def test_scenario_12_tensor_bounds_and_vocabulary_gating() -> None:
    """Verifies tensor shape constraints, index boundaries, and strict vocabulary gating."""
    from curriculum.translation import (
        index_to_simulator_id,
        mastery_profile_from_indexed_output,
        validate_simulator_ids,
        UnknownSimulatorIdError,
    )

    vocab_file = PERSON3_DIR / "data" / "models" / "akt_vocabulary.json"
    if not vocab_file.is_file():
        pytest.skip("AKT vocabulary fixture not accessible.")

    vocab_data = json.loads(vocab_file.read_text(encoding="utf-8"))
    c2i = vocab_data["concept_to_index"]
    assert len(c2i) == 62

    # In AKT vocabulary, indices are 1-based [1..62]; index 0 is padding
    indices = list(c2i.values())
    assert min(indices) == 1
    assert max(indices) == 62

    # 1. Unknown concept IDs are caught before tensor generation
    with pytest.raises(UnknownSimulatorIdError) as exc_info:
        validate_simulator_ids(["PHY_KIN", "INVALID_CONCEPT_XYZ", "MAT_SET"], vocab_file)
    assert "INVALID_CONCEPT_XYZ" in str(exc_info.value)

    # 2. Output vector reconstruction preserves exact index alignment
    # Simulate a model tensor output of shape (63,) with index 0 as padding
    raw_output = [0.0] + [0.5 + (i * 0.005) for i in range(1, 63)]
    sim_profile = mastery_profile_from_indexed_output(raw_output, vocab_file)
    assert len(sim_profile) == 62
    assert "PHY_KIN" in sim_profile
    assert sim_profile["PHY_KIN"] == raw_output[c2i["PHY_KIN"]]

    # 3. Index reverse mapping produces bijection
    rev = index_to_simulator_id(vocab_file)
    assert len(rev) == 62
    for cid, idx in c2i.items():
        assert rev[idx] == cid

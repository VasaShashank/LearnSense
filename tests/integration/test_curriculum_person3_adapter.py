"""
Person 3 learner-graph adapter against the live curriculum API boundary (Person 2).

Seeds through the real mounted routes (``POST /api/curriculum/seed``) over a
tmp-dir repository, then loads ``KnowledgeGraphAdapter`` through the *same*
repository/service object the routes read from.  Proves:

* integrated mode reads the canonical graph the API just persisted -- never a
  simulator CSV and never sample data;
* adapter answers agree with API responses (prerequisites, learning order);
* an unseeded store is an explicit ``CanonicalGraphUnavailableError``, not a
  silent fallback;
* a battery of adapter queries leaves the API-visible store byte-identical
  (read-only guarantee);
* requesting a curriculum id the store does not hold names what *is* held.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from backend.app import app
from backend.routes.curriculum import get_service
from backend.services.curriculum_service import CurriculumService
from curriculum.learner_adapter import (
    CanonicalGraphUnavailableError,
    KnowledgeGraphAdapter,
)
from curriculum.repository import CurriculumRepository
from tests.integration.test_curriculum_api import API_SPEC

CURRICULUM_ID = API_SPEC["curriculum_id"]


@pytest.fixture
def repo(tmp_path):
    """Repository rooted in tmp so the suite never touches ``storage/``."""
    return CurriculumRepository(base_dir=str(tmp_path / "curriculum_store"))


@pytest.fixture
def client(repo):
    """The real app; every request builds a fresh service over the tmp repo."""
    app.dependency_overrides[get_service] = lambda: CurriculumService(repository=repo)
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.pop(get_service, None)


@pytest.fixture
def seeded_client(client):
    response = client.post(
        "/api/curriculum/seed",
        json={"spec": API_SPEC, "reviewer_id": "adapter_teacher"},
    )
    assert response.status_code == 200, response.text
    return client


def concept_ids_by_name(client):
    response = client.get("/api/curriculum/concepts")
    assert response.status_code == 200
    return {item["name"]: item["concept_id"] for item in response.json()["concepts"]}


def test_adapter_loads_graph_the_api_persisted(seeded_client, repo):
    adapter = KnowledgeGraphAdapter.from_repository(repo, CURRICULUM_ID)

    api_names = concept_ids_by_name(seeded_client)
    assert sorted(api_names.values()) == adapter.concept_ids
    assert adapter.curriculum_id == CURRICULUM_ID

    # Same service object the routes use must see the identical graph.
    service = CurriculumService(repository=repo)
    assert service.get_graph().content_fingerprint() == adapter.graph_fingerprint()


def test_adapter_prerequisite_answers_match_api_responses(seeded_client, repo):
    adapter = KnowledgeGraphAdapter.from_repository(repo, CURRICULUM_ID)
    names = concept_ids_by_name(seeded_client)

    for name, concept_id in names.items():
        response = seeded_client.get(
            f"/api/curriculum/concepts/{concept_id}/prerequisites",
            params={"depth": 1},
        )
        assert response.status_code == 200, response.text
        slice_ = response.json()
        api_prereqs = {
            rel["source"]
            for rel in slice_["relationships"]
            if rel["type"] == "prerequisite_of"
            and rel["target"] == concept_id
            and rel["status"] == "accepted"
        }
        assert api_prereqs == set(adapter.get_direct_prerequisites(concept_id))
        assert name  # fixture sanity: the loop really ran


def test_adapter_learning_order_equals_api_learning_order(seeded_client, repo):
    adapter = KnowledgeGraphAdapter.from_repository(repo, CURRICULUM_ID)
    response = seeded_client.get("/api/curriculum/learning-order")
    assert response.status_code == 200
    assert adapter.get_all_concept_ids() == response.json()["order"]


def test_unseeded_store_is_an_explicit_error_never_sample_data(repo, tmp_path):
    with pytest.raises(CanonicalGraphUnavailableError) as excinfo:
        KnowledgeGraphAdapter.from_repository(repo, CURRICULUM_ID)

    assert CURRICULUM_ID in str(excinfo.value)
    # The failed load created nothing on disk: no store, no synthetic substitute.
    assert not (tmp_path / "curriculum_store").exists() or not any(
        (tmp_path / "curriculum_store").rglob("*.json")
    )


def test_unknown_curriculum_id_names_the_curricula_actually_held(seeded_client, repo):
    with pytest.raises(CanonicalGraphUnavailableError) as excinfo:
        KnowledgeGraphAdapter.from_repository(repo, "curriculum_that_never_existed")

    message = str(excinfo.value)
    assert "curriculum_that_never_existed" in message
    assert CURRICULUM_ID in message  # the remedy: which curriculum is stored


def test_adapter_queries_leave_the_api_store_untouched(seeded_client, repo):
    status_before = seeded_client.get("/api/curriculum/status").json()
    adapter = KnowledgeGraphAdapter.from_repository(repo, CURRICULUM_ID)
    fingerprint_before = adapter.graph_fingerprint()

    for concept_id in adapter.concept_ids:
        adapter.get_concept(concept_id)
        adapter.get_direct_prerequisites(concept_id)
        adapter.get_direct_dependents(concept_id)
        adapter.get_all_ancestor_prerequisites(concept_id)
        adapter.get_all_descendant_dependents(concept_id)
        adapter.evaluate_prerequisite_readiness(concept_id, {concept_id: 0.6})
        adapter.get_remediation_sequence(concept_id, {})
    adapter.topological_sort()
    adapter.validate_graph()
    adapter.detect_cycles()
    adapter.find_invalid_prerequisite_references()

    assert adapter.graph_fingerprint() == fingerprint_before
    status_after = seeded_client.get("/api/curriculum/status").json()
    assert status_after == status_before
    # A brand-new service over the same store still fingerprints identically.
    fresh = KnowledgeGraphAdapter.from_repository(
        CurriculumService(repository=repo).repository, CURRICULUM_ID
    )
    assert fresh.graph_fingerprint() == fingerprint_before


def test_adapter_and_api_report_the_same_validation_verdict(seeded_client, repo):
    service = CurriculumService(repository=repo)
    adapter = KnowledgeGraphAdapter.from_repository(repo, CURRICULUM_ID)

    adapter_report = adapter.validate_graph()
    service_report = service.validate_graph()

    assert adapter_report.is_valid is True
    assert adapter_report.is_valid == service_report.is_valid
    assert adapter_report.error_count == service_report.error_count
    assert adapter_report.warning_count == service_report.warning_count
    assert [issue.code for issue in adapter_report.issues] == [
        issue.code for issue in service_report.issues
    ]


def test_adapter_translation_service_integration(seeded_client, repo):
    """End-to-end integration between curriculum service graph and mastery translation."""
    from curriculum.translation import (
        translate_mastery_profile,
        validate_simulator_ids,
        UnknownSimulatorIdError,
    )

    service = CurriculumService(repository=repo)
    graph = service.get_graph()
    adapter = KnowledgeGraphAdapter.from_repository(repo, CURRICULUM_ID)

    # 1. Unknown simulator ID rejection (no index-zero fallback)
    vocab = {"CHE_EQM": 0, "PHY_KIN": 1}
    with pytest.raises(UnknownSimulatorIdError) as exc_info:
        validate_simulator_ids(["CHE_EQM", "UNKNOWN_SIM_ID"], vocab)
    assert "UNKNOWN_SIM_ID" in str(exc_info.value)

    # 2. Translate mastery profile using canonical graph from API service
    names = concept_ids_by_name(seeded_client)
    # Map a known simulator ID to an active canonical concept in the seeded graph
    velocity_canonical_id = names["Velocity"]
    concept_map = {"PHY_VEL": velocity_canonical_id}
    sim_profile = {"PHY_VEL": 0.85, "CHE_UNMAPPED": 0.40}

    result = translate_mastery_profile(
        sim_profile,
        graph=graph,
        concept_map=concept_map,
    )

    # Graph identity and fingerprint consistency
    assert result.graph_curriculum_id == CURRICULUM_ID
    assert result.graph_fingerprint == adapter.graph_fingerprint()
    assert result.canonical_mastery == {velocity_canonical_id: 0.85}
    assert result.original_profile == sim_profile
    assert result.unresolved_simulator_ids == ["CHE_UNMAPPED"]
    assert result.is_complete is False
    assert result.coverage_rate == 0.5


def test_service_get_adapter_and_integration_factory(seeded_client, repo):
    """Test CurriculumService provides duck-typed adapter and production integration factory."""
    service = CurriculumService(repository=repo, curriculum_id=CURRICULUM_ID)
    
    # 1. get_adapter() returns duck-compliant adapter
    adapter = service.get_adapter()
    assert len(adapter) == 4
    assert adapter.concept_ids
    assert adapter.fingerprint == service.get_graph().content_fingerprint()

    # 2. get_integration_factory() creates working factory in production mode
    factory = service.get_integration_factory(mode="production")
    created_adapter = factory.create_adapter(CURRICULUM_ID)
    assert created_adapter.fingerprint == adapter.fingerprint

    # 3. evaluate_readiness() evaluates prerequisite DAG via service
    concepts = service.list_concepts()
    by_name = {c["name"]: c["concept_id"] for c in concepts}
    pos_id = by_name["Position"]
    vel_id = by_name["Velocity"]

    # Position is root
    r_pos = service.evaluate_readiness(pos_id, {})
    assert r_pos["is_ready"] is True

    # Velocity needs Position >= 0.50
    r_vel_fail = service.evaluate_readiness(vel_id, {pos_id: 0.25})
    assert r_vel_fail["is_ready"] is False
    assert pos_id in r_vel_fail["remediation_needed"]

    r_vel_pass = service.evaluate_readiness(vel_id, {pos_id: 0.80})
    assert r_vel_pass["is_ready"] is True


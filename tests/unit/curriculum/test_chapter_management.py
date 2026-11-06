"""
Unit and API integration tests for Teacher Chapter Management (Person 2).
"""

import pytest
from fastapi.testclient import TestClient

from backend.app import app
from backend.routes.curriculum import get_service
from backend.services.curriculum_service import CurriculumService
from curriculum.repository import CurriculumRepository
from curriculum.seed import load_spec, seed_curriculum


@pytest.fixture
def isolated_service(tmp_path):
    """Provide an isolated CurriculumService and Repository backed by tmp_path."""
    repo = CurriculumRepository(base_dir=str(tmp_path / "curriculum"))
    spec = load_spec("curriculum/data/jee_curriculum_spec.json")
    seed_curriculum(spec, repository=repo)
    service = CurriculumService(repository=repo)

    app.dependency_overrides[get_service] = lambda: service
    try:
        yield service
    finally:
        app.dependency_overrides.pop(get_service, None)


def test_list_chapters(isolated_service):
    service = isolated_service
    chapters = service.list_chapters()
    assert len(chapters) > 0

    # Test filtering by subject
    physics_chapters = service.list_chapters(subject="physics")
    assert all(c["subject"] == "physics" for c in physics_chapters)
    assert len(physics_chapters) > 0


def test_create_and_update_chapter(isolated_service):
    service = isolated_service
    chapter = service.create_chapter(
        chapter_id="ch_experimental_optics",
        name="Experimental Optics",
        subject="physics",
        class_levels=["class_12"],
        description="Optics lab exercises and instruments.",
        reviewer_id="teacher_1",
    )
    assert chapter["chapter_id"] == "ch_experimental_optics"
    assert chapter["name"] == "Experimental Optics"
    assert chapter["subject"] == "physics"

    # Duplicate creation rejected
    with pytest.raises(ValueError, match="already exists"):
        service.create_chapter(
            chapter_id="ch_experimental_optics",
            name="Experimental Optics",
            subject="physics",
        )

    # Update chapter
    updated = service.update_chapter(
        chapter_id="ch_experimental_optics",
        name="Advanced Experimental Optics",
        description="Updated optics lab curriculum.",
        reviewer_id="teacher_2",
    )
    assert updated["name"] == "Advanced Experimental Optics"
    assert updated["description"] == "Updated optics lab curriculum."


def test_reassign_concept_chapter(isolated_service):
    service = isolated_service
    # Get a physics concept
    concepts = service.list_concepts(subject="physics", limit=1)
    assert len(concepts) > 0
    cid = concepts[0]["concept_id"]

    # Reassign to valid chapter
    res = service.reassign_concept_chapter(
        concept_id=cid,
        chapter_id="ch_new_mechanics",
        reviewer_id="teacher_1",
        note="Reassigned for curriculum refinement",
    )
    assert res["chapter_id"] == "ch_new_mechanics"


def test_reassign_subject_mismatch(isolated_service):
    service = isolated_service
    # Create chemistry chapter
    service.create_chapter(
        chapter_id="ch_organic_reactions",
        name="Organic Reactions",
        subject="chemistry",
    )
    # Get a physics concept
    concepts = service.list_concepts(subject="physics", limit=1)
    cid = concepts[0]["concept_id"]

    # Attempting to assign physics concept to chemistry chapter must fail
    with pytest.raises(ValueError, match="Subject mismatch"):
        service.reassign_concept_chapter(
            concept_id=cid,
            chapter_id="ch_organic_reactions",
            reviewer_id="teacher_1",
        )


def test_chapter_api_endpoints(isolated_service):
    client = TestClient(app)

    # 1. GET /api/curriculum/chapters
    res = client.get("/api/curriculum/chapters")
    assert res.status_code == 200
    data = res.json()
    assert "chapters" in data
    assert data["count"] > 0

    # 2. POST /api/curriculum/chapters
    create_payload = {
        "chapter_id": "ch_api_test_chapter",
        "name": "API Test Chapter",
        "subject": "mathematics",
        "class_levels": ["class_11"],
        "description": "Test chapter via REST API",
        "reviewer_id": "test_teacher",
    }
    res = client.post("/api/curriculum/chapters", json=create_payload)
    assert res.status_code in {200, 201}
    assert res.json()["chapter_id"] == "ch_api_test_chapter"

    # 3. PUT /api/curriculum/chapters/{chapter_id}
    update_payload = {
        "name": "Updated API Test Chapter",
        "description": "Updated description",
        "reviewer_id": "test_teacher_2",
    }
    res = client.put("/api/curriculum/chapters/ch_api_test_chapter", json=update_payload)
    assert res.status_code == 200
    assert res.json()["name"] == "Updated API Test Chapter"

    # 4. PUT /api/curriculum/concepts/{concept_id}/chapter
    concepts_res = client.get("/api/curriculum/concepts?subject=mathematics&limit=1")
    cid = concepts_res.json()["concepts"][0]["concept_id"]

    reassign_payload = {
        "chapter_id": "ch_api_test_chapter",
        "reviewer_id": "test_teacher_3",
        "note": "Reassigned via REST endpoint",
    }
    res = client.put(f"/api/curriculum/concepts/{cid}/chapter", json=reassign_payload)
    assert res.status_code == 200
    assert res.json()["chapter_id"] == "ch_api_test_chapter"


def test_chapter_taxonomy_and_deprecated_filtering(isolated_service):
    """Verify authoritative chapter names, category separation, and deprecated filtering."""
    client = TestClient(app)

    # 1. Active chapters default (78 chapters)
    res = client.get("/api/curriculum/chapters")
    assert res.status_code == 200
    data = res.json()
    assert data["count"] == 78
    assert len(data["chapters"]) == 78

    ch_by_id = {c["chapter_id"]: c for c in data["chapters"]}
    # Check taxonomy examples from prompt
    assert ch_by_id["ch_chemical_bonding"]["name"] == "Chemical Bonding"
    assert ch_by_id["ch_chemical_bonding"]["category"] == "Inorganic Chemistry"
    assert ch_by_id["ch_chemical_bonding"]["subject"] == "chemistry"

    assert ch_by_id["ch_coordination_compounds"]["name"] == "Coordination Compounds"
    assert ch_by_id["ch_coordination_compounds"]["category"] == "Inorganic Chemistry"

    assert ch_by_id["ch_hydrocarbons"]["name"] == "Hydrocarbons"
    assert ch_by_id["ch_hydrocarbons"]["category"] == "Organic Chemistry"

    assert ch_by_id["ch_atomic_structure"]["name"] == "Atomic Structure"
    assert ch_by_id["ch_atomic_structure"]["category"] == "Physical Chemistry"

    assert ch_by_id["ch_binomial_theorem"]["name"] == "Binomial Theorem"
    assert ch_by_id["ch_binomial_theorem"]["category"] == "Algebra"

    assert ch_by_id["ch_circles"]["name"] == "Circles"
    assert ch_by_id["ch_circles"]["category"] == "Coordinate Geometry"

    assert ch_by_id["ch_laws_of_motion"]["name"] == "Laws of Motion"
    assert ch_by_id["ch_laws_of_motion"]["category"] == "Mechanics"

    # 2. Verify deprecated chapters are excluded by default but accessible via include_deprecated=true
    assert "ch_coordinate_geometry_conics" not in ch_by_id
    assert "ch_ray_and_wave_optics" not in ch_by_id

    res_all = client.get("/api/curriculum/chapters?include_deprecated=true")
    assert res_all.status_code == 200
    all_data = res_all.json()
    assert all_data["count"] == 80
    all_ch_by_id = {c["chapter_id"]: c for c in all_data["chapters"]}
    assert "ch_coordinate_geometry_conics" in all_ch_by_id
    assert "ch_ray_and_wave_optics" in all_ch_by_id
    assert all_ch_by_id["ch_coordinate_geometry_conics"]["is_deprecated"] is True
    assert all_ch_by_id["ch_ray_and_wave_optics"]["is_deprecated"] is True


def test_status_endpoint_metrics_and_provenance_coverage(isolated_service):
    """Verify /api/curriculum/status and /api/curriculum/quality metrics."""
    client = TestClient(app)

    status_res = client.get("/api/curriculum/status")
    assert status_res.status_code == 200
    st = status_res.json()
    assert st["concept_count"] == 89
    assert st["active_concept_count"] == 87
    assert st["active_jee_main_2027_concepts"] == 84
    assert st["legacy_retained_concepts"] == 3
    assert "pending_review" in st
    assert "unmapped_mapping_candidates" in st
    assert st["pending_review"] == st["unmapped_mapping_candidates"]

    quality_res = client.get("/api/curriculum/quality")
    assert quality_res.status_code == 200
    q = quality_res.json()
    cm = q["concept_metrics"]
    assert cm["total"] == 89
    assert cm["active"] == 87
    assert cm["deprecated"] == 2
    assert cm["provenance_coverage"] == 1.0
    assert cm["hashed_excerpt_coverage"] >= 0.94

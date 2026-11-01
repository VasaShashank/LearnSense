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

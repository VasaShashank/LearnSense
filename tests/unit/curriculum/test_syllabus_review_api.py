"""
Unit and API integration tests for Teacher Syllabus Mapping Review (Person 2).
"""

from fastapi.testclient import TestClient

from backend.app import app
from backend.services.curriculum_service import CurriculumService


def test_list_syllabus_items():
    service = CurriculumService()
    items = service.list_syllabus_items()
    assert len(items) == 135

    # Filter by subject
    math_items = service.list_syllabus_items(subject="mathematics")
    assert len(math_items) == 29
    assert all(m["subject"] == "mathematics" for m in math_items)

    # Filter by status
    exact_items = service.list_syllabus_items(status="exact_match")
    assert len(exact_items) > 0


def test_syllabus_coverage_summary():
    service = CurriculumService()
    summary = service.syllabus_coverage_summary()
    assert summary["has_crosswalk"] is True
    assert summary["summary"]["total_syllabus_items"] == 135
    assert summary["summary"]["coverage_percentage"] == 100.0


def test_review_syllabus_mapping():
    service = CurriculumService()
    res = service.review_syllabus_mapping(
        syllabus_item_id="syl_math_u01_01",
        status="exact_match",
        canonical_concept_ids=["cc_test_dummy"],
        reviewer_id="teacher_expert",
        review_notes="Verified against NCERT Class 11 Chapter 1",
    )
    assert res["syllabus_item_id"] == "syl_math_u01_01"
    assert res["reviewer"] == "teacher_expert"
    assert res["canonical_concept_ids"] == ["cc_test_dummy"]


def test_syllabus_api_endpoints():
    client = TestClient(app)

    # 1. GET /api/curriculum/syllabus/items
    res = client.get("/api/curriculum/syllabus/items")
    assert res.status_code == 200
    data = res.json()
    assert data["count"] == 135
    assert len(data["items"]) == 135

    # 2. GET /api/curriculum/syllabus/coverage
    cov_res = client.get("/api/curriculum/syllabus/coverage")
    assert cov_res.status_code == 200
    cov_data = cov_res.json()
    assert cov_data["has_crosswalk"] is True
    assert cov_data["summary"]["total_syllabus_items"] == 135

    # 3. POST /api/curriculum/syllabus/review
    review_payload = {
        "syllabus_item_id": "syl_math_u04_01",
        "status": "exact_match",
        "canonical_concept_ids": ["cc_custom_verified"],
        "reviewer_id": "lead_math_teacher",
        "review_notes": "Permutations and Combinations verified",
    }
    rev_res = client.post("/api/curriculum/syllabus/review", json=review_payload)
    assert rev_res.status_code == 200
    assert rev_res.json()["reviewer"] == "lead_math_teacher"

    # 4. Unknown syllabus item 404
    bad_payload = {
        "syllabus_item_id": "non_existent_syl_item",
        "status": "exact_match",
        "canonical_concept_ids": [],
        "reviewer_id": "teacher",
    }
    bad_res = client.post("/api/curriculum/syllabus/review", json=bad_payload)
    assert bad_res.status_code == 404

"""
Data integrity regression tests for Person 2 curriculum knowledge graph.

Verifies:
1. Protected curriculum files (spec, crosswalk, live graph) are never modified by test operations.
2. Test-created concepts cannot leak into persistent curriculum files.
3. Test-created chapters cannot leak into persistent curriculum files.
4. Failed tests still clean up temporary storage and dependency overrides.
5. Parallel / isolated test environments do not share mutable state or leak to persistent storage.
"""

from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path
from typing import Dict

import pytest
from fastapi.testclient import TestClient

from backend.app import app
from backend.routes.curriculum import get_service
from backend.services.curriculum_service import CurriculumService
from curriculum.repository import CurriculumRepository
from curriculum.seed import load_spec, seed_curriculum

PROTECTED_FILES = [
    Path("curriculum/data/jee_curriculum_spec.json"),
    Path("curriculum/data/jee_main_2027_crosswalk.json"),
    Path("storage/curriculum/graphs/jee_class_11_12.json"),
]


def file_sha256(path: Path) -> str:
    """Calculate SHA-256 hash of a file if it exists, or empty string."""
    if not path.exists():
        return ""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def snapshot_hashes() -> Dict[Path, str]:
    """Capture current hashes of all protected curriculum files."""
    return {p: file_sha256(p) for p in PROTECTED_FILES}


class TestCurriculumDataIntegrity:
    """Verify that curriculum test harnesses maintain absolute data integrity."""

    def test_protected_curriculum_files_unchanged_by_test_operations(self, tmp_path):
        """Perform extensive mutations in isolated test environments and verify persistent files are unchanged."""
        hashes_before = snapshot_hashes()

        # Set up isolated repository & copy crosswalk
        repo = CurriculumRepository(base_dir=str(tmp_path / "curriculum"))
        spec = load_spec("curriculum/data/jee_curriculum_spec.json")
        seed_curriculum(spec, repository=repo)

        tmp_crosswalk = tmp_path / "jee_main_2027_crosswalk.json"
        shutil.copy2(Path("curriculum/data/jee_main_2027_crosswalk.json"), tmp_crosswalk)

        service = CurriculumService(repository=repo, crosswalk_path=tmp_crosswalk)
        app.dependency_overrides[get_service] = lambda: service

        try:
            # 1. Create chapters
            service.create_chapter(
                chapter_id="ch_integrity_test_chapter",
                name="Integrity Test Chapter",
                subject="physics",
                class_levels=["class_11"],
                description="Chapter created during regression test",
                reviewer_id="integrity_tester",
            )

            # 2. Reassign a concept
            physics_concepts = service.list_concepts(subject="physics", limit=1)
            assert len(physics_concepts) > 0
            cid = physics_concepts[0]["concept_id"]
            service.reassign_concept_chapter(
                concept_id=cid,
                chapter_id="ch_integrity_test_chapter",
                reviewer_id="integrity_tester",
                note="Test reassignment",
            )

            # 3. Review syllabus mapping
            service.review_syllabus_mapping(
                syllabus_item_id="syl_math_u01_01",
                status="exact_match",
                canonical_concept_ids=["cc_integrity_dummy"],
                reviewer_id="integrity_reviewer",
                review_notes="Integrity test note",
            )

            # 4. API endpoint review call
            client = TestClient(app)
            payload = {
                "syllabus_item_id": "syl_math_u04_01",
                "status": "exact_match",
                "canonical_concept_ids": ["cc_api_integrity_dummy"],
                "reviewer_id": "api_integrity_reviewer",
                "review_notes": "API test note",
            }
            res = client.post("/api/curriculum/syllabus/review", json=payload)
            assert res.status_code == 200

        finally:
            app.dependency_overrides.pop(get_service, None)

        # Verify all protected files are 100% bit-for-bit unchanged
        hashes_after = snapshot_hashes()
        for p in PROTECTED_FILES:
            assert hashes_before[p] == hashes_after[p], (
                f"PROTECTED FILE MUTATED: {p}\n"
                f"  Before: {hashes_before[p]}\n"
                f"  After:  {hashes_after[p]}"
            )

    def test_chapter_creation_does_not_leak_to_persistent_storage(self, tmp_path):
        """Verify that chapters created in isolated services never leak into persistent JSON."""
        persistent_graph_path = Path("storage/curriculum/graphs/jee_class_11_12.json")
        graph_before = json.loads(persistent_graph_path.read_text(encoding="utf-8"))
        persistent_chapter_ids = {
            c["chapter_id"] for c in graph_before["concepts"].values()
        }
        meta_chapters = set(graph_before.get("metadata", {}).get("chapters", {}).keys())

        # Create isolated chapter
        repo = CurriculumRepository(base_dir=str(tmp_path / "curriculum"))
        spec = load_spec("curriculum/data/jee_curriculum_spec.json")
        seed_curriculum(spec, repository=repo)
        service = CurriculumService(repository=repo)

        leak_chapter_id = "ch_leak_detection_test_xyz"
        service.create_chapter(
            chapter_id=leak_chapter_id,
            name="Leak Detection Chapter",
            subject="chemistry",
        )

        # Inspect persistent storage file directly from disk
        graph_after = json.loads(persistent_graph_path.read_text(encoding="utf-8"))
        assert leak_chapter_id not in graph_after.get("metadata", {}).get("chapters", {}), (
            f"LEAK DETECTED: {leak_chapter_id} found in persistent graph metadata"
        )
        for cid, c in graph_after["concepts"].items():
            assert c["chapter_id"] != leak_chapter_id, (
                f"LEAK DETECTED: concept {cid} was assigned {leak_chapter_id} in persistent graph"
            )

    def test_syllabus_review_does_not_leak_to_persistent_crosswalk(self, tmp_path):
        """Verify that syllabus reviews performed in isolated test service do not alter persistent crosswalk."""
        persistent_crosswalk_path = Path("curriculum/data/jee_main_2027_crosswalk.json")
        cw_before = persistent_crosswalk_path.read_text(encoding="utf-8")

        tmp_crosswalk = tmp_path / "crosswalk.json"
        shutil.copy2(persistent_crosswalk_path, tmp_crosswalk)

        repo = CurriculumRepository(base_dir=str(tmp_path / "curriculum"))
        service = CurriculumService(repository=repo, crosswalk_path=tmp_crosswalk)

        # Mutate in test
        dummy_id = "cc_test_leak_check_999"
        service.review_syllabus_mapping(
            syllabus_item_id="syl_math_u01_01",
            status="exact_match",
            canonical_concept_ids=[dummy_id],
            reviewer_id="leak_checker",
        )

        # Persistent file on disk must be identical and not contain dummy_id
        cw_after = persistent_crosswalk_path.read_text(encoding="utf-8")
        assert cw_before == cw_after
        assert dummy_id not in cw_after

    def test_failed_tests_still_clean_up_dependency_overrides(self, tmp_path):
        """Verify that when a test encounters an unhandled exception, overrides are cleaned up."""
        repo = CurriculumRepository(base_dir=str(tmp_path / "curriculum"))
        service = CurriculumService(repository=repo)

        # Simulate fixture context with failure
        def run_failing_operation():
            app.dependency_overrides[get_service] = lambda: service
            try:
                raise RuntimeError("Simulated unhandled test failure")
            finally:
                app.dependency_overrides.pop(get_service, None)

        with pytest.raises(RuntimeError, match="Simulated unhandled test failure"):
            run_failing_operation()

        # Dependency override must be absent
        assert get_service not in app.dependency_overrides

    def test_parallel_isolated_environments_do_not_share_state(self, tmp_path):
        """Verify that two concurrent test runs with distinct tmp_paths cannot contaminate each other."""
        dir_a = tmp_path / "run_a"
        dir_b = tmp_path / "run_b"

        spec = load_spec("curriculum/data/jee_curriculum_spec.json")

        repo_a = CurriculumRepository(base_dir=str(dir_a / "curriculum"))
        seed_curriculum(spec, repository=repo_a)
        service_a = CurriculumService(repository=repo_a)

        repo_b = CurriculumRepository(base_dir=str(dir_b / "curriculum"))
        seed_curriculum(spec, repository=repo_b)
        service_b = CurriculumService(repository=repo_b)

        # Mutate env A only
        service_a.create_chapter(
            chapter_id="ch_env_a_exclusive",
            name="Exclusive to A",
            subject="mathematics",
        )

        chapters_a = {c["chapter_id"] for c in service_a.list_chapters()}
        chapters_b = {c["chapter_id"] for c in service_b.list_chapters()}

        assert "ch_env_a_exclusive" in chapters_a
        assert "ch_env_a_exclusive" not in chapters_b, "State leaked from env A to env B!"


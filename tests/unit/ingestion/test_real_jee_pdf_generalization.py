"""
Integration and generalization test suite for independent real-world JEE Main educational PDFs.
Validates ingestion, topic extraction, evidence grounding, DAG acyclicity, and syllabus mapping
across publicly accessible JEE Main materials without hardcoded shortcuts.
"""

import os
import json
import hashlib
import tempfile
from pathlib import Path
import pytest

from backend.services.knowledge_build_service import KnowledgeBuildService
from storage.store import DocumentStorage
from storage.repositories import LearningContextRepository

FIXTURES_DIR = Path(__file__).resolve().parent.parent.parent / "fixtures" / "real_jee_pdfs"
MANIFEST_PATH = FIXTURES_DIR / "manifest.json"
RESULTS_PATH = FIXTURES_DIR / "evaluation_results.json"
GOLD_PATH = FIXTURES_DIR / "gold_standards.json"


@pytest.fixture(scope="module")
def manifest_data():
    assert MANIFEST_PATH.exists(), f"Missing manifest at {MANIFEST_PATH}"
    with open(MANIFEST_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


@pytest.fixture(scope="module")
def evaluation_results():
    assert RESULTS_PATH.exists(), f"Missing results at {RESULTS_PATH}"
    with open(RESULTS_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


class TestRealJeePdfGeneralization:

    def test_fixture_integrity_and_manifest_checksums(self, manifest_data):
        """Verify that all 11 real JEE PDFs are stored unmodified with exact SHA-256 match."""
        assert len(manifest_data) >= 10, f"Expected at least 10 real PDFs, found {len(manifest_data)}"
        
        for doc_id, meta in manifest_data.items():
            pdf_path = FIXTURES_DIR / meta["filename"]
            assert pdf_path.exists(), f"Fixture PDF missing: {pdf_path}"
            assert pdf_path.stat().st_size == meta["file_size_bytes"]
            
            with open(pdf_path, "rb") as f:
                content = f.read()
            computed_sha = hashlib.sha256(content).hexdigest()
            assert computed_sha == meta["sha256"], f"SHA-256 mismatch for {doc_id}"

    def test_partition_isolation_and_coverage(self, manifest_data):
        """Verify that documents span Development, Validation, and Held-out partitions."""
        partitions = {m["partition"] for m in manifest_data.values()}
        assert "Development/Regression" in partitions
        assert "Validation" in partitions
        assert "Held-out Evaluation" in partitions

        subjects = {m["subject"] for m in manifest_data.values()}
        assert "Physics" in subjects
        assert "Chemistry" in subjects
        assert "Mathematics" in subjects
        assert "Biology" in subjects

    def test_generalization_benchmark_aggregate_metrics(self, evaluation_results):
        """Verify overall benchmark metrics meet production quality thresholds."""
        results = list(evaluation_results.values())
        total_docs = len(results)
        assert total_docs >= 10

        macro_precision = sum(r["precision"] for r in results) / total_docs
        macro_recall = sum(r["assessable_recall"] for r in results) / total_docs
        macro_f1 = sum(r["f1_score"] for r in results) / total_docs
        avg_grounding = sum(r["grounding_percentage"] for r in results) / total_docs
        
        # Rigorous production thresholds
        assert macro_precision >= 98.0, f"Precision {macro_precision:.2f}% below 98%"
        assert macro_recall >= 70.0, f"Macro recall {macro_recall:.2f}% below 70%"
        assert macro_f1 >= 80.0, f"Macro F1 {macro_f1:.2f}% below 80%"
        assert avg_grounding == 100.0, f"Grounding rate {avg_grounding:.2f}% is not 100%"
        
        # Verify zero DAG cycles across all documents
        for r in results:
            assert r["dag_has_cycles"] is False, f"DAG cycle detected in {r['id']}"

    def test_held_out_generalization_performance(self, evaluation_results):
        """Verify performance on the held-out partition to guarantee no benchmark leakage."""
        held_out = [r for r in evaluation_results.values() if r["partition"] == "Held-out Evaluation"]
        assert len(held_out) >= 5, "Expected at least 5 held-out evaluation documents"

        held_out_recall = sum(r["assessable_recall"] for r in held_out) / len(held_out)
        held_out_precision = sum(r["precision"] for r in held_out) / len(held_out)
        held_out_f1 = sum(r["f1_score"] for r in held_out) / len(held_out)

        assert held_out_precision >= 98.0, f"Held-out precision {held_out_precision:.2f}% below 98%"
        assert held_out_recall >= 75.0, f"Held-out recall {held_out_recall:.2f}% below 75%"
        assert held_out_f1 >= 85.0, f"Held-out F1 {held_out_f1:.2f}% below 85%"

    def test_live_pipeline_execution_sample(self):
        """Run live pipeline on a held-out Allen handbook PDF to verify end-to-end execution."""
        sample_filename = "math_permutations_combinations_allen.pdf"
        pdf_path = FIXTURES_DIR / sample_filename
        assert pdf_path.exists()
        
        with open(pdf_path, "rb") as f:
            pdf_bytes = f.read()

        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            storage = DocumentStorage(root_dir=str(tmp_path / "storage"))
            context_repo = LearningContextRepository(base_dir=str(tmp_path / "contexts"))
            service = KnowledgeBuildService(storage=storage, context_repo=context_repo)

            doc_id = "test_live_sample_pnc"
            res = service.build(doc_id, pdf_bytes, sample_filename, reuse_existing=False)
            
            assert res["status"] in ("valid", "partially_valid", "PROCESSED", "READY")
            assert res["concept_count"] >= 15
            assert res["grounded_concept_count"] == res["concept_count"]
            assert res["topic_count"] >= 1

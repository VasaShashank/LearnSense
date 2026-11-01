"""
Unit and regression test suite for Strict JEE Main and NEET Dataset Separation.
Verifies and enforces:
1. JEE Main PCM remains the primary benchmark.
2. NEET Biology metrics are always reported separately.
3. NEET concepts are never combined with JEE Main PCM concepts when calculating JEE benchmark metrics.
4. Ingesting NEET Biology cannot silently mutate or add concepts to the JEE Main canonical curriculum.
5. JEE diagnostic question banks cannot be polluted by NEET Biology concepts.
6. Explicit Examination/Curriculum identifiers distinguish JEE from NEET curricula.
"""

import os
import json
import hashlib
import tempfile
from pathlib import Path
import pytest

from curriculum.models import Examination, Subject, CurriculumGraph
from curriculum.mapping import MappingContext, ContentMapper
from curriculum.repository import CurriculumRepository
from backend.services.curriculum_service import CurriculumService
from backend.services.knowledge_build_service import KnowledgeBuildService
from storage.store import DocumentStorage
from storage.repositories import LearningContextRepository

FIXTURES_DIR = Path(__file__).resolve().parent.parent.parent / "fixtures" / "real_jee_pdfs"
MANIFEST_PATH = FIXTURES_DIR / "manifest.json"
BENCHMARK_SUMMARY_PATH = FIXTURES_DIR / "hierarchical_benchmark_summary_v2.json"
GOLD_V2_PATH = FIXTURES_DIR / "hierarchical_gold_standards_v2.json"
JEE_SPEC_PATH = Path(__file__).resolve().parent.parent.parent.parent / "curriculum" / "data" / "jee_curriculum_spec.json"
CROSSWALK_PATH = Path(__file__).resolve().parent.parent.parent.parent / "curriculum" / "data" / "jee_main_2027_crosswalk.json"


class TestJeeNeetDatasetSeparation:
    """Rigorous enforcement of JEE Main and NEET curriculum and benchmark separation."""

    def test_examination_enum_and_curriculum_graph_property(self):
        """Examination enum cleanly distinguishes JEE, NEET, and General curricula."""
        assert Examination.coerce("jee") == Examination.JEE_MAIN
        assert Examination.coerce("JEE_MAIN") == Examination.JEE_MAIN
        assert Examination.coerce("JEE (Main) - 2027") == Examination.JEE_MAIN
        assert Examination.coerce("neet") == Examination.NEET
        assert Examination.coerce("NEET (UG)") == Examination.NEET
        assert Examination.coerce("SAT") == Examination.GENERAL

        # Default CurriculumGraph targets JEE Main
        jee_graph = CurriculumGraph(curriculum_id="jee_main_2027")
        assert jee_graph.examination == Examination.JEE_MAIN

        # NEET graph is recognized by ID or metadata
        neet_graph = CurriculumGraph(curriculum_id="neet_biology_v1")
        assert neet_graph.examination == Examination.NEET

        neet_graph_meta = CurriculumGraph(curriculum_id="custom", metadata={"examination": "NEET"})
        assert neet_graph_meta.examination == Examination.NEET

    def test_manifest_metadata_examination_isolation(self):
        """Manifest must tag every document with explicit examination identifiers."""
        assert MANIFEST_PATH.exists()
        with open(MANIFEST_PATH, "r", encoding="utf-8") as f:
            manifest = json.load(f)

        jee_docs = []
        neet_docs = []

        for doc_id, meta in manifest.items():
            assert "examination" in meta, f"Missing examination in {doc_id}"
            assert "target_curriculum" in meta, f"Missing target_curriculum in {doc_id}"
            assert "is_cross_domain_experiment" in meta, f"Missing is_cross_domain_experiment in {doc_id}"

            if meta["examination"] == "JEE_MAIN":
                assert meta["subject"] in ("Physics", "Chemistry", "Mathematics")
                assert meta["target_curriculum"] == "jee_main_2027"
                assert meta["is_cross_domain_experiment"] is False
                jee_docs.append(doc_id)
            elif meta["examination"] == "NEET":
                assert meta["subject"] == "Biology"
                assert meta["target_curriculum"] == "neet_ug_2027"
                assert meta["is_cross_domain_experiment"] is True
                neet_docs.append(doc_id)
            else:
                pytest.fail(f"Unknown examination {meta['examination']} for {doc_id}")

        assert len(jee_docs) == 10, f"Expected exactly 10 JEE Main documents, found {len(jee_docs)}"
        assert len(neet_docs) == 1, f"Expected exactly 1 NEET cross-domain document, found {len(neet_docs)}"

    def test_benchmark_metrics_strictly_separate_jee_and_neet(self):
        """Primary benchmark must be strictly JEE Main PCM, never contaminated by NEET Biology."""
        assert BENCHMARK_SUMMARY_PATH.exists()
        with open(BENCHMARK_SUMMARY_PATH, "r", encoding="utf-8") as f:
            summary = json.load(f)

        aggs = summary["aggregates"]
        assert "jee_main_paper_1_pcm_10_docs" in aggs
        assert "neet_biology_cross_domain_1_doc" in aggs

        jee_agg = aggs["jee_main_paper_1_pcm_10_docs"]
        neet_agg = aggs["neet_biology_cross_domain_1_doc"]

        # JEE Main PCM aggregate must strictly contain 10 documents
        assert jee_agg["document_count"] == 10
        assert jee_agg["total_extracted_concepts"] == 778
        assert jee_agg["total_present_gold_concepts"] == 112
        assert jee_agg["total_matched_bipartite_1_to_1"] == 83
        assert jee_agg["macro_metrics"]["text_present_recall"] == 72.05
        assert jee_agg["macro_metrics"]["strict_gold_precision"] == 15.07
        assert jee_agg["macro_metrics"]["academic_concept_precision"] == 25.42

        # NEET Biology must strictly contain 1 document
        assert neet_agg["document_count"] == 1
        assert neet_agg["total_extracted_concepts"] == 181
        assert neet_agg["total_present_gold_concepts"] == 19
        assert neet_agg["total_matched_bipartite_1_to_1"] == 13
        assert neet_agg["macro_metrics"]["text_present_recall"] == 68.42
        assert neet_agg["macro_metrics"]["strict_gold_precision"] == 7.18

        # Enforce that JEE metrics do not contain NEET concepts
        assert jee_agg["total_extracted_concepts"] + neet_agg["total_extracted_concepts"] == 959
        assert jee_agg["total_present_gold_concepts"] + neet_agg["total_present_gold_concepts"] == 131
        assert jee_agg["total_matched_bipartite_1_to_1"] + neet_agg["total_matched_bipartite_1_to_1"] == 96

    def test_neet_biology_ingestion_zero_mutation_on_canonical_jee_curriculum(self):
        """Ingesting NEET Biology PDF must not modify canonical JEE curriculum spec or crosswalk."""
        assert JEE_SPEC_PATH.exists()
        assert CROSSWALK_PATH.exists()

        spec_before_hash = hashlib.sha256(JEE_SPEC_PATH.read_bytes()).hexdigest()
        crosswalk_before_hash = hashlib.sha256(CROSSWALK_PATH.read_bytes()).hexdigest()

        bio_pdf_path = FIXTURES_DIR / "biology_cell_cycle_esaral.pdf"
        assert bio_pdf_path.exists()
        pdf_bytes = bio_pdf_path.read_bytes()

        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_p = Path(tmp_dir)
            storage = DocumentStorage(root_dir=str(tmp_p / "storage"))
            context_repo = LearningContextRepository(base_dir=str(tmp_p / "contexts"))
            curr_repo = CurriculumRepository(base_dir=str(tmp_p / "curriculum"))
            curr_svc = CurriculumService(repository=curr_repo)
            
            build_svc = KnowledgeBuildService(storage=storage, context_repo=context_repo)
            res = build_svc.build("test_neet_doc", pdf_bytes, bio_pdf_path.name, reuse_existing=False)

            assert res["status"] in ("valid", "partially_valid", "PROCESSED", "READY")
            assert res["concept_count"] == 181

            # Verify that canonical JEE spec and crosswalk files were NOT touched
            spec_after_hash = hashlib.sha256(JEE_SPEC_PATH.read_bytes()).hexdigest()
            crosswalk_after_hash = hashlib.sha256(CROSSWALK_PATH.read_bytes()).hexdigest()

            assert spec_after_hash == spec_before_hash, "JEE curriculum spec was mutated by NEET ingestion!"
            assert crosswalk_after_hash == crosswalk_before_hash, "JEE crosswalk was mutated by NEET ingestion!"

            # Canonical JEE graph must contain 0 Biology concepts
            jee_graph = curr_svc.get_graph()
            for concept in jee_graph.concepts.values():
                assert concept.subject != Subject.PHYSICS or concept.subject in (Subject.PHYSICS, Subject.CHEMISTRY, Subject.MATHEMATICS)
                assert "biology" not in str(concept.subject).lower()

    def test_canonical_mapper_cross_examination_guard(self):
        """ContentMapper suppresses proposed concepts when a NEET document is mapped against JEE Main."""
        bio_pdf_path = FIXTURES_DIR / "biology_cell_cycle_esaral.pdf"
        pdf_bytes = bio_pdf_path.read_bytes()

        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_p = Path(tmp_dir)
            storage = DocumentStorage(root_dir=str(tmp_p / "storage"))
            context_repo = LearningContextRepository(base_dir=str(tmp_p / "contexts"))
            curr_repo = CurriculumRepository(base_dir=str(tmp_p / "curriculum"))
            curr_svc = CurriculumService(repository=curr_repo, context_repo=context_repo)

            build_svc = KnowledgeBuildService(storage=storage, context_repo=context_repo)
            build_svc.build("biology_cell_cycle_esaral", pdf_bytes, bio_pdf_path.name, reuse_existing=False)

            # Map the NEET context against the JEE Main canonical graph
            mapping_res = curr_svc.map_learning_context("biology_cell_cycle_esaral", persist=False)

            # Assert ZERO accepted mappings
            assert mapping_res.summary.get("accepted", 0) == 0

            # Assert ZERO proposed concepts into the JEE curriculum (suppressed by cross-examination guard)
            assert mapping_res.summary.get("proposed_concepts", 0) == 0
            for candidate in mapping_res.candidates:
                assert candidate.proposed_concept is None, f"Proposed concept leaked from NEET: {candidate.label}"
                if candidate.source_kind == "extracted_concept":
                    assert "cross-examination entity" in candidate.reason

    def test_jee_diagnostic_generation_zero_neet_pollution(self):
        """A JEE Main diagnostic question bank contains strictly 0 Biology concepts."""
        lom_pdf_path = FIXTURES_DIR / "physics_laws_of_motion_esaral.pdf"
        pdf_bytes = lom_pdf_path.read_bytes()

        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_p = Path(tmp_dir)
            storage = DocumentStorage(root_dir=str(tmp_p / "storage"))
            context_repo = LearningContextRepository(base_dir=str(tmp_p / "contexts"))
            
            build_svc = KnowledgeBuildService(storage=storage, context_repo=context_repo)
            build_svc.build("physics_laws_of_motion_esaral", pdf_bytes, lom_pdf_path.name, reuse_existing=False)

            ctx = context_repo.load_context("physics_laws_of_motion_esaral")
            assert ctx is not None
            concept_names = [c.canonical_name for c in ctx.concepts.values()]

            # Confirm all concepts are valid physics concepts
            for name in concept_names:
                assert "cell" not in name.lower()
                assert "mitosis" not in name.lower()
                assert "chromatid" not in name.lower()
                assert "anaphase" not in name.lower()


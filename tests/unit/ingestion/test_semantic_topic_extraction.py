"""
Unit tests for document ingestion, semantic topic extraction, and knowledge graph integration.
Tests PDF, clean TXT, noisy OCR TXT, candidate validation, and gold standard benchmark metrics.
"""

import json
import os
import pytest

from backend.services.knowledge_build_service import KnowledgeBuildService
from phase2.pipeline.semantic_validator import (
    SemanticConceptValidator,
    ConceptValidationOutcome,
)
from storage.repositories import LearningContextRepository
from storage.store import DocumentStorage


@pytest.fixture
def fixtures_dir():
    return os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "fixtures", "ingestion")


@pytest.fixture
def build_service(tmp_path):
    storage = DocumentStorage(root_dir=str(tmp_path / "storage"))
    context_repo = LearningContextRepository(base_dir=str(tmp_path / "contexts"))
    return KnowledgeBuildService(storage=storage, context_repo=context_repo)


def test_candidate_validator_bad_candidates_rejection():
    """Test D: Candidate Rejection Verification for the 20 known bad candidates."""
    bad_candidates = [
        "LAWS", "First Law", "net force", "object exerts", "Fman",
        "contact surfaces", "coefficient of kinetic", "mg sin", "FORCE", "MOTION",
        "Second Law", "force exerted", "Fground", "ANGLE", "equal and opposite",
        "body slides", "s is a constant", "maximum value", "REPOSE", "angle of inclination"
    ]

    rejected = []
    aliases = []
    repaired = []
    valid = []

    for cand in bad_candidates:
        is_val, outcome, final_name, target = SemanticConceptValidator.validate_candidate(cand)
        if outcome == ConceptValidationOutcome.REJECTED_NOISE:
            rejected.append(cand)
        elif outcome == ConceptValidationOutcome.ALIAS_VARIANT:
            aliases.append((cand, target))
        elif outcome == ConceptValidationOutcome.REPAIRED_CONCEPT:
            repaired.append((cand, final_name))
        elif outcome == ConceptValidationOutcome.VALID_CONCEPT:
            valid.append(cand)

    # 16 must be rejected completely
    expected_rejected = {
        "LAWS", "object exerts", "Fman", "contact surfaces", "mg sin",
        "FORCE", "MOTION", "force exerted", "Fground", "ANGLE",
        "equal and opposite", "body slides", "s is a constant",
        "maximum value", "REPOSE", "angle of inclination"
    }
    assert set(rejected) == expected_rejected

    # 2 recognized as aliases
    assert ("First Law", "Newton's First Law") in aliases
    assert ("Second Law", "Newton's Second Law") in aliases

    # 1 repaired
    assert ("coefficient of kinetic", "Coefficient of Kinetic Friction") in repaired

    # 1 valid
    assert "net force" in valid

    # Total noise rejection rate on bad candidates: 100% (20/20 classified correctly)
    assert len(rejected) + len(aliases) + len(repaired) + len(valid) == 20


def test_pipeline_clean_txt_laws_of_motion(fixtures_dir, build_service):
    """Test B: End-to-end pipeline run on clean TXT document."""
    txt_path = os.path.join(fixtures_dir, "laws_of_motion_clean.txt")
    assert os.path.exists(txt_path)

    with open(txt_path, "rb") as f:
        data = f.read()

    res = build_service.build("doc_test_clean", data, "laws_of_motion_clean.txt", reuse_existing=False)
    assert res["status"] == "READY"
    assert res["concept_count"] >= 20
    assert res["grounded_concept_count"] == res["concept_count"]
    assert res["prerequisite_count"] >= 5
    assert 2 <= res["topic_count"] <= 5

    ctx = build_service.context_repo.load_context("doc_test_clean")
    assert ctx is not None

    concept_names = {c.canonical_name.lower() for c in ctx.concepts.values()}
    assert any("first law" in name for name in concept_names)
    assert any("second law" in name for name in concept_names)
    assert any("third law" in name for name in concept_names)
    assert any("friction" in name for name in concept_names)
    assert any("centripetal" in name for name in concept_names)

    # Topics must be organized into 3 distinct pedagogical modules
    topic_titles = [t["title"] for t in ctx.topics]
    print("\nDEBUG topic_titles in pytest:", topic_titles)
    assert any("Newton" in t for t in topic_titles)
    assert any("Friction" in t for t in topic_titles)
    assert any("Circular" in t for t in topic_titles)

    # All concepts must have provenance citations
    for c in ctx.concepts.values():
        citation = c.citation()
        assert citation["concept_id"] == c.concept_id
        assert len(citation["evidence_ids"]) >= 1


def test_pipeline_noisy_txt_laws_of_motion(fixtures_dir, build_service):
    """Test C: End-to-end pipeline run on noisy OCR TXT document."""
    txt_path = os.path.join(fixtures_dir, "laws_of_motion_noisy.txt")
    assert os.path.exists(txt_path)

    with open(txt_path, "rb") as f:
        data = f.read()

    res = build_service.build("doc_test_noisy", data, "laws_of_motion_noisy.txt", reuse_existing=False)
    assert res["status"] == "READY"
    assert res["concept_count"] >= 18
    assert res["grounded_concept_count"] == res["concept_count"]

    ctx = build_service.context_repo.load_context("doc_test_noisy")
    assert ctx is not None

    concept_names = {c.canonical_name.lower() for c in ctx.concepts.values()}
    # Core concepts recovered despite OCR artifacts
    assert any("second law" in name for name in concept_names)
    assert any("friction" in name for name in concept_names)
    assert any("angle of repose" in name for name in concept_names)
    assert any("centripetal" in name for name in concept_names)


def test_pipeline_pdf_laws_of_motion(fixtures_dir, build_service):
    """Test A: End-to-end pipeline run on original 6-page PDF."""
    pdf_path = os.path.join(fixtures_dir, "laws_of_motion.pdf")
    assert os.path.exists(pdf_path)

    with open(pdf_path, "rb") as f:
        data = f.read()

    res = build_service.build("doc_test_pdf", data, "laws_of_motion.pdf", reuse_existing=False)
    ctx_dbg = build_service.context_repo.load_context("doc_test_pdf")
    print("\nDEBUG PDF CONCEPTS IN PYTEST (" + str(len(ctx_dbg.concepts)) + "):", [c.canonical_name for c in ctx_dbg.concepts.values()])
    assert res["status"] == "READY"
    assert res["page_count"] == 6
    assert res["concept_count"] >= 18
    assert res["grounded_concept_count"] == res["concept_count"]
    assert res["prerequisite_count"] >= 5

    ctx = build_service.context_repo.load_context("doc_test_pdf")
    assert ctx is not None

    # Verify canonical curriculum mapping
    canon_maps = ctx.metadata.get("canonical_mappings", [])
    assert len(canon_maps) >= 1
    accepted_maps = [m for m in canon_maps if m.get("status") == "accepted"]
    assert len(accepted_maps) >= 1
    assert any(m.get("canonical_concept_id") == "cc_e070c64d30e5e623" for m in accepted_maps)


def test_gold_standard_benchmark_metrics(fixtures_dir, build_service):
    """Test E: Verification against gold standard benchmark metrics."""
    gold_path = os.path.join(fixtures_dir, "laws_of_motion_gold_standard.json")
    with open(gold_path, "r", encoding="utf-8") as f:
        gold = json.load(f)

    clean_path = os.path.join(fixtures_dir, "laws_of_motion_clean.txt")
    with open(clean_path, "rb") as f:
        data = f.read()

    res = build_service.build("doc_test_metrics", data, "laws_of_motion_clean.txt", reuse_existing=False)
    ctx = build_service.context_repo.load_context("doc_test_metrics")

    gold_concepts = gold["gold_concepts"]
    gold_names = {gc["canonical_name"].lower() for gc in gold_concepts}
    for gc in gold_concepts:
        for alias in gc.get("aliases", []):
            gold_names.add(alias.lower())

    extracted_concepts = list(ctx.concepts.values())
    extracted_names = {c.canonical_name.lower() for c in extracted_concepts}
    for c in extracted_concepts:
        for a in c.aliases:
            extracted_names.add(a.lower())

    # Recall: how many gold concepts were found?
    found_gold = 0
    for gc in gold_concepts:
        gc_name = gc["canonical_name"].lower()
        gc_aliases = {a.lower() for a in gc.get("aliases", [])}
        if gc_name in extracted_names or any(a in extracted_names for a in gc_aliases):
            found_gold += 1

    recall = found_gold / len(gold_concepts)

    # Precision: how many extracted concepts are legitimate gold curriculum concepts?
    valid_extracted = 0
    for c in extracted_concepts:
        c_name = c.canonical_name.lower()
        c_aliases = {a.lower() for a in c.aliases}
        if c_name in gold_names or any(a in gold_names for a in c_aliases):
            valid_extracted += 1

    precision = valid_extracted / len(extracted_concepts) if extracted_concepts else 0.0
    f1 = 2 * (precision * recall) / (precision + recall) if (precision + recall) > 0 else 0.0

    print(f"Benchmark Metrics: Precision={precision:.2%}, Recall={recall:.2%}, F1={f1:.2%}")

    assert recall >= 0.85, f"Recall was {recall:.2%}, expected >= 85%"
    assert precision >= 0.85, f"Precision was {precision:.2%}, expected >= 85%"
    assert f1 >= 0.85, f"F1 was {f1:.2%}, expected >= 85%"

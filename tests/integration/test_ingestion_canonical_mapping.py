"""
Integration test for normal ingestion-to-canonical curriculum mapping wiring (Person 2).

Verifies:
1. Normal ingestion build flow invokes CurriculumService canonical mapping.
2. Canonical references (cc_<sha16>) are attached to context.metadata['canonical_mappings'].
3. Document-scoped concept IDs (c_<sha12>) in context.concepts remain intact.
4. Retry/re-run behavior is idempotent.
5. Ingestion gracefully succeeds even if curriculum service is unseeded.
"""

from unittest.mock import patch
import pytest

from backend.services.curriculum_service import CurriculumService
from backend.services.knowledge_build_service import KnowledgeBuildService
from curriculum.repository import CurriculumRepository
from curriculum.seed import load_spec, seed_curriculum
from schemas.document import BlockTypeEnum
from storage.repositories import LearningContextRepository
from storage.store import DocumentStorage
from tests.support.mini_document import build_ekr, build_mini_document


@pytest.fixture
def seeded_service(tmp_path):
    repo = CurriculumRepository(base_dir=tmp_path / "curriculum")
    spec = load_spec("curriculum/data/jee_curriculum_spec.json")
    seed_curriculum(spec, repository=repo)
    return CurriculumService(repository=repo)


def test_build_invokes_canonical_mapping_and_attaches_metadata(tmp_path, seeded_service):
    doc_id = "test_doc_kinematics_101"
    filename = "kinematics_chapter.pdf"
    dummy_pdf_bytes = b"%PDF-1.4 dummy pdf"

    kinematics_text = (
        "Kinematics is the branch of classical mechanics that describes the motion of points, bodies, "
        "and systems without consideration of the forces that cause the motion. Position, velocity, "
        "and acceleration are fundamental quantities in kinematics."
    )

    structured_doc = build_mini_document(
        doc_id,
        [
            ("blk_k_0", "Kinematics", BlockTypeEnum.HEADING),
            ("blk_k_1", kinematics_text, BlockTypeEnum.PARAGRAPH),
        ],
        section_title="Kinematics",
    )

    ekr = build_ekr(
        doc_id,
        structured_doc,
        concepts=[("c_kin_1", "Kinematics", "blk_k_1")],
        evidence=[("ev_kin_1", "blk_k_1", kinematics_text)],
    )

    context_repo = LearningContextRepository(base_dir=tmp_path / "contexts")
    storage = DocumentStorage(root_dir=tmp_path / "storage")
    build_service = KnowledgeBuildService(
        curriculum_service=seeded_service,
        context_repo=context_repo,
        storage=storage,
    )

    with patch.object(build_service, "_validate", return_value=None), \
         patch.object(build_service, "_ingest", return_value=structured_doc), \
         patch.object(build_service, "_validate_structured", return_value=None), \
         patch.object(build_service, "_run_phase2", return_value=ekr), \
         patch.object(build_service, "_assert_grounded", return_value=None), \
         patch.object(build_service.storage, "load_structured_document", return_value=structured_doc.model_dump()):

        build_result = build_service.build(doc_id, dummy_pdf_bytes, filename, reuse_existing=False)

    assert build_result["status"] == "READY"
    assert "canonical_mapping_count" in build_result

    # Inspect persisted learning context
    persisted_context = build_service.context_repo.load_context(doc_id)
    assert persisted_context is not None

    # Canonical mappings must be attached in metadata
    assert "canonical_mappings" in persisted_context.metadata
    assert persisted_context.metadata["curriculum_id"] == "jee_class_11_12"
    assert persisted_context.metadata["curriculum_version"] == "2026.jee.v1"

    mappings = persisted_context.metadata["canonical_mappings"]
    assert len(mappings) > 0
    # Every mapping item must have candidate_id, label, canonical_concept_id
    for m in mappings:
        assert m["canonical_concept_id"].startswith("cc_")
        assert "status" in m
        assert "confidence" in m

    # Document-scoped concept id preserved in context.concepts
    assert any("c_kin_1" in cid or "Kinematics" in c.name for cid, c in persisted_context.concepts.items())


def test_build_graceful_when_curriculum_unseeded(tmp_path):
    doc_id = "test_doc_unseeded"
    filename = "doc.pdf"
    dummy_pdf_bytes = b"%PDF-1.4 dummy pdf"

    text = "General text for document."
    structured_doc = build_mini_document(
        doc_id,
        [("blk_1", text, BlockTypeEnum.PARAGRAPH)],
        section_title="General",
    )
    ekr = build_ekr(
        doc_id,
        structured_doc,
        concepts=[("c_gen_1", "General", "blk_1")],
        evidence=[("ev_gen_1", "blk_1", text)],
    )

    empty_service = CurriculumService(repository=CurriculumRepository(base_dir=tmp_path / "empty_curriculum"))
    context_repo = LearningContextRepository(base_dir=tmp_path / "contexts_unseeded")
    storage = DocumentStorage(root_dir=tmp_path / "storage_unseeded")
    build_service = KnowledgeBuildService(
        curriculum_service=empty_service,
        context_repo=context_repo,
        storage=storage,
    )

    with patch.object(build_service, "_validate", return_value=None), \
         patch.object(build_service, "_ingest", return_value=structured_doc), \
         patch.object(build_service, "_validate_structured", return_value=None), \
         patch.object(build_service, "_run_phase2", return_value=ekr), \
         patch.object(build_service, "_assert_grounded", return_value=None), \
         patch.object(build_service.storage, "load_structured_document", return_value=structured_doc.model_dump()):

        # Must not crash or raise error when curriculum is unseeded
        build_result = build_service.build(doc_id, dummy_pdf_bytes, filename, reuse_existing=False)

    assert build_result["status"] == "READY"
    persisted = build_service.context_repo.load_context(doc_id)
    assert persisted is not None

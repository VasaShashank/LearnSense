"""
Hardening and Property/Adversarial/Failure-Injection tests for Phase 2 Milestone M4.
"""

import json
import pytest
from schemas.document import StructuredDocument
from phase2.pipeline.runner import Phase2PipelineRunner
from phase2.storage import KnowledgeStorageManager, generate_id_map_migration
from evaluation.phase2_eval import evaluate_knowledge_representation


def test_hard_invariants_and_determinism_across_fixtures():
    runner = Phase2PipelineRunner()

    with open("tests/fixtures/phase2/textbook.json", "r", encoding="utf-8") as f:
        data = json.load(f)

    doc1 = StructuredDocument.model_validate(data)
    doc2 = StructuredDocument.model_validate(data)

    ekr1 = runner.process(doc1)
    ekr2 = runner.process(doc2)

    # Hard invariant check
    assert ekr1.qc_report["passed_qc"] is True

    # Determinism test
    assert ekr1.knowledge_document_id == ekr2.knowledge_document_id
    assert [c.concept_id for c in ekr1.concepts] == [c.concept_id for c in ekr2.concepts]
    assert [r.relationship_id for r in ekr1.relationships] == [r.relationship_id for r in ekr2.relationships]


def test_adversarial_prompt_injection():
    with open("tests/fixtures/phase2/injection_attempts.json", "r", encoding="utf-8") as f:
        data = json.load(f)

    doc = StructuredDocument.model_validate(data)
    runner = Phase2PipelineRunner()
    ekr = runner.process(doc)

    assert ekr.status in ("completed", "completed_with_warnings")
    # Verify no ungrounded secrets leaked or executed
    assert len(ekr.concepts) == 0 or all(c.canonical_name != "SECRET" for c in ekr.concepts)


def test_metamorphic_block_renaming():
    with open("tests/fixtures/phase2/simple_text.json", "r", encoding="utf-8") as f:
        data = json.load(f)

    doc1 = StructuredDocument.model_validate(data)

    # Rename block ID in doc2
    data_renamed = json.loads(json.dumps(data))
    data_renamed["pages"][0]["blocks"][0]["block_id"] = "renamed_blk_99"
    doc2 = StructuredDocument.model_validate(data_renamed)

    runner = Phase2PipelineRunner()
    ekr1 = runner.process(doc1)
    ekr2 = runner.process(doc2)

    # Canonical concept names should remain invariant under block ID renaming
    names1 = [c.canonical_name for c in ekr1.concepts]
    names2 = [c.canonical_name for c in ekr2.concepts]
    assert names1 == names2


def test_storage_and_id_map_migration():
    with open("tests/fixtures/phase2/textbook.json", "r", encoding="utf-8") as f:
        data = json.load(f)

    doc = StructuredDocument.model_validate(data)
    runner = Phase2PipelineRunner()
    ekr = runner.process(doc)

    storage = KnowledgeStorageManager("tests/tmp_knowledge")
    saved_dir = storage.store_knowledge_representation(ekr)
    assert saved_dir is not None

    id_map = generate_id_map_migration(ekr, ekr)
    assert len(id_map) == len(ekr.concepts)


def test_golden_eval_script():
    with open("tests/fixtures/phase2/textbook.json", "r", encoding="utf-8") as f:
        data = json.load(f)

    doc = StructuredDocument.model_validate(data)
    runner = Phase2PipelineRunner()
    ekr = runner.process(doc)

    golden = {"concepts": ["Newton's Second Law", "Force"]}
    metrics = evaluate_knowledge_representation(ekr, golden)

    assert "concept_precision" in metrics
    assert "concept_f1" in metrics

"""
Unit and Integration tests for Milestone M1 (Stages 1-3, Stage 9, Runner).
"""

import json
import pytest
from schemas.document import StructuredDocument
from phase2.pipeline.runner import Phase2PipelineRunner
from phase2.pipeline.stage1_normalize import run_stage1_normalize
from phase2.pipeline.stage2_context import run_stage2_context


def test_m1_walking_skeleton_simple_fixture():
    with open("tests/fixtures/phase2/simple_text.json", "r", encoding="utf-8") as f:
        data = json.load(f)

    doc = StructuredDocument.model_validate(data)
    runner = Phase2PipelineRunner()
    ekr = runner.process(doc)

    assert ekr.source_document_id == "doc_simple"
    assert ekr.knowledge_document_id == "kr_doc_simple"
    assert len(ekr.educational_units) > 0
    assert ekr.status in ("completed", "completed_with_warnings")
    assert ekr.qc_report.get("passed_qc") is True


def test_m1_textbook_profile():
    with open("tests/fixtures/phase2/textbook.json", "r", encoding="utf-8") as f:
        data = json.load(f)

    doc = StructuredDocument.model_validate(data)
    norm_doc = run_stage1_normalize(doc)
    doc_ctx = run_stage2_context(norm_doc)

    assert doc_ctx.profile.genre == "textbook"
    assert "sec_01" in doc_ctx.section_paths

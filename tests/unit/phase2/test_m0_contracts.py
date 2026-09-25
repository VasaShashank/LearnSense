"""
Unit and Contract tests for Phase 2 Milestone M0.
"""

import json
import glob
import pytest
from schemas.document import StructuredDocument
from phase2.models import EducationalKnowledgeRepresentation
from phase2.contract import validate_structured_document_input, export_output_json_schema
from phase2.utils.id_generator import (
    generate_concept_id,
    generate_skill_id,
    generate_unit_id,
    generate_evidence_id,
)
from phase2.adapters.nlp_adapters import Tier01DeterministicAdapter, MockLLMAdapter


def test_schema_models():
    ekr = EducationalKnowledgeRepresentation(
        knowledge_document_id="kr_001",
        source_document_id="doc_001"
    )
    assert ekr.schema_version == "2.0.0"
    schema = export_output_json_schema()
    assert "properties" in schema


def test_id_generator_determinism():
    c_id1 = generate_concept_id("doc_1", "Newton's Second Law")
    c_id2 = generate_concept_id("doc_1", "newton's second law")
    assert c_id1 == c_id2

    s_id1 = generate_skill_id("doc_1", "apply", ["c_1", "c_2"])
    s_id2 = generate_skill_id("doc_1", "apply", ["c_2", "c_1"])
    assert s_id1 == s_id2


def test_contract_validation_fixtures():
    fixture_files = glob.glob("tests/fixtures/phase2/*.json")
    assert len(fixture_files) >= 12

    for filepath in fixture_files:
        with open(filepath, "r", encoding="utf-8") as f:
            data = json.load(f)
        doc = StructuredDocument.model_validate(data)
        warnings = validate_structured_document_input(doc)
        assert isinstance(warnings, list)


def test_nlp_adapters():
    adapter = Tier01DeterministicAdapter()
    keywords = adapter.extract_keywords("Force is defined as mass times acceleration")
    assert "Force" in keywords
    role = adapter.classify_text_role("Force is defined as...")
    assert role == "definition"

    mock_llm = MockLLMAdapter()
    res = mock_llm.generate_json_response("Extract force", {"concept": "force"})
    assert res == {"concept": "force"}

"""
Shared-contract compatibility (Person 2).

The hand-rolled subset validator in ``curriculum/contract.py`` is the runtime
path; ``jsonschema`` is optional corroboration only (skipped when absent).
These tests pin the properties consumers rely on:

* ``to_contract_record()`` emits exactly the contract's property set,
* violations carry locatable paths and keyword names -- nothing is silently
  ignored, and unsupported schema keywords are *reported* rather than dropped,
* schema lookup order (env dir -> repo -> sibling ``References`` archive) and a
  loud error when no schema exists,
* name-derived ids and dangling prerequisites -- the checks JSON Schema cannot
  express -- are enforced with their own keywords.
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from curriculum.contract import (
    CONCEPT_SCHEMA_NAME,
    QUESTION_SCHEMA_NAME,
    ContractSchemaNotFoundError,
    check_id_stability,
    contract_schema_paths,
    load_contract_schema,
    validate_against_schema,
    validate_concept_graph,
    validate_concept_record,
    validate_question_record,
    validate_reference_integrity,
    validate_with_jsonschema,
)
from curriculum.ids import slugify
from curriculum.models import CanonicalConcept


class _FakeConcept:
    """Duck type exposing only what ``validate_concept_graph`` reads."""

    def __init__(self, record):
        self._record = record

    def to_contract_record(self):
        return dict(self._record)


@pytest.fixture
def concept_record(pilot_graph):
    return pilot_graph.concepts[pilot_graph.concept_ids()[0]].to_contract_record()


def make_question(**overrides):
    question = {
        "question_id": "q_001",
        "question_type": "single_choice",
        "prompt": "Which velocity-time graph shows constant acceleration?",
        "assesses": [{"concept_id": "cc_0000000000000000", "weight": 1.0, "role": "primary"}],
        "status": "active",
    }
    question.update(overrides)
    return question


class TestSchemaResolution:
    @pytest.mark.skipif(
        contract_schema_paths()[CONCEPT_SCHEMA_NAME] is None,
        reason="shared-contract archive not present beside the repo",
    )
    def test_reference_schemas_resolve_and_carry_the_documented_shape(self):
        paths = contract_schema_paths()
        assert paths[CONCEPT_SCHEMA_NAME] is not None
        assert paths[QUESTION_SCHEMA_NAME] is not None

        schema = load_contract_schema(CONCEPT_SCHEMA_NAME)
        assert load_contract_schema("concept_schema") == schema  # extension optional
        assert schema["additionalProperties"] is False
        assert set(schema["required"]) == {"concept_id", "name", "description", "status"}
        assert len(schema["properties"]) == 10

    def test_env_dir_wins_over_the_bundled_search_path(self, monkeypatch, tmp_path):
        custom = {"type": "object", "title": "custom-contract-dir"}
        (tmp_path / CONCEPT_SCHEMA_NAME).write_text(json.dumps(custom), encoding="utf-8")
        monkeypatch.setenv("LEARNSENSE_CONTRACT_DIR", str(tmp_path))

        assert contract_schema_paths()[CONCEPT_SCHEMA_NAME] == tmp_path / CONCEPT_SCHEMA_NAME
        assert load_contract_schema(CONCEPT_SCHEMA_NAME) == custom

    def test_missing_schema_raises_with_the_search_path(self):
        with pytest.raises(ContractSchemaNotFoundError) as excinfo:
            load_contract_schema("nope_schema.json")
        message = str(excinfo.value)
        assert "nope_schema.json" in message
        assert "Searched" in message
        assert "LEARNSENSE_CONTRACT_DIR" in message


class TestConceptRecordContract:
    def test_record_is_exactly_the_contract_property_set(self, concept_record):
        schema = load_contract_schema(CONCEPT_SCHEMA_NAME)
        assert set(concept_record) == set(schema["properties"])
        assert len(concept_record) == 10
        assert concept_record["concept_id"].startswith("cc_")
        assert concept_record["status"] in schema["properties"]["status"]["enum"]

    def test_record_round_trips_losslessly(self, concept_record):
        restored = CanonicalConcept.from_contract_record(concept_record)
        assert restored.to_contract_record() == concept_record

    def test_valid_record_passes(self, concept_record):
        result = validate_concept_record(concept_record)
        assert result.ok
        assert result.error_count == 0
        assert result.violations == []
        assert result.checked == 1
        assert result.unsupported_keywords == set()
        result.raise_if_invalid()  # must not raise

    def test_missing_required_field_is_reported(self, concept_record):
        bad = dict(concept_record)
        bad.pop("description")
        result = validate_concept_record(bad)
        assert not result.ok
        assert {violation.keyword for violation in result.violations} == {"required"}
        with pytest.raises(ValueError, match="contract violation"):
            result.raise_if_invalid()

    def test_unexpected_property_is_locatable(self, concept_record):
        bad = dict(concept_record)
        bad["extra_field"] = 1
        result = validate_concept_record(bad)
        assert not result.ok
        violation = result.violations[0]
        assert violation.path == "/extra_field"
        assert violation.keyword == "additionalProperties"
        assert violation.message == "unexpected property 'extra_field'"
        assert "status" in violation.expected  # allowed set is reported too

    @pytest.mark.parametrize(
        "field, value, keyword, path",
        [
            ("metadata", "not-an-object", "type", "/metadata"),
            ("status", "retired", "enum", "/status"),
            ("tags", "physics", "type", "/tags"),
            ("concept_id", "", "minLength", "/concept_id"),
            ("tags", ["a", "a"], "uniqueItems", "/tags[1]"),
            ("prerequisite_concept_ids", ["cc_1", "cc_1"], "uniqueItems", "/prerequisite_concept_ids[1]"),
            ("chapter_id", 7, "type", "/chapter_id"),
        ],
    )
    def test_scalar_and_array_violations(self, concept_record, field, value, keyword, path):
        bad = dict(concept_record)
        bad[field] = value
        result = validate_concept_record(bad)
        assert not result.ok
        assert any(
            violation.keyword == keyword and violation.path == path
            for violation in result.violations
        ), result.messages()

    def test_nested_source_ref_violation_keeps_its_index(self, concept_record):
        bad = dict(concept_record)
        bad["source_refs"] = [{"source_id": "doc_1"}, {"locator": "p.1"}]
        result = validate_concept_record(bad)
        violation = next(v for v in result.violations if v.keyword == "required")
        assert violation.path == "/source_refs[1]/source_id"


class TestGraphExportChecks:
    def test_seeded_graph_export_validates(self, pilot_graph):
        result = validate_concept_graph(pilot_graph)
        assert result.ok
        assert result.error_count == 0
        assert result.checked == 10
        assert result.unsupported_keywords == set()

    def test_duplicate_concept_id_in_export_is_reported(self, concept_record):
        shadow = dict(concept_record)
        fake = SimpleNamespace(
            concepts={"k1": _FakeConcept(concept_record), "k2": _FakeConcept(shadow)},
            concept_ids=lambda: ["k1", "k2"],
        )
        result = validate_concept_graph(fake)
        assert {violation.keyword for violation in result.violations} == {"duplicate_id"}
        violation = result.violations[0]
        assert violation.path == "/1/concept_id"
        assert "also used by record 0" in violation.message

    def test_duplicate_source_id_within_one_concept_is_reported(self, concept_record):
        shadow = dict(concept_record)
        shadow["source_refs"] = [
            {"source_id": "doc_1", "locator": "p.1"},
            {"source_id": "doc_1", "locator": "p.2"},
        ]
        fake = SimpleNamespace(
            concepts={"k": _FakeConcept(shadow)}, concept_ids=lambda: ["k"]
        )
        result = validate_concept_graph(fake)
        assert {violation.keyword for violation in result.violations} == {"duplicate_source"}
        assert result.violations[0].path == "/0/source_refs"


class TestReferenceIntegrity:
    def test_seeded_graph_records_pass(self, pilot_graph):
        records = [
            pilot_graph.concepts[cid].to_contract_record()
            for cid in pilot_graph.concept_ids()
        ]
        result = validate_reference_integrity(records)
        assert result.ok
        assert result.checked == 10

    def test_dangling_prerequisite_is_locatable(self, concept_record):
        bad = dict(concept_record)
        bad["prerequisite_concept_ids"] = ["cc_missing_reference"]
        result = validate_reference_integrity([bad])
        assert not result.ok
        assert len(result.violations) == 1
        violation = result.violations[0]
        assert violation.keyword == "reference_integrity"
        assert violation.path == "/0/prerequisite_concept_ids/0"
        assert violation.got == "cc_missing_reference"

    def test_known_id_set_resolves_references_from_outside_the_batch(self, concept_record):
        bad = dict(concept_record)
        bad["prerequisite_concept_ids"] = ["cc_elsewhere"]
        result = validate_reference_integrity(
            [bad], known_concept_ids={bad["concept_id"], "cc_elsewhere"}
        )
        assert result.ok

    def test_name_derived_id_is_flagged_from_within_reference_checks(self, concept_record):
        bad = dict(concept_record)
        bad["concept_id"] = f"cc_{slugify(concept_record['name'])}"
        result = validate_reference_integrity([bad])
        assert any(violation.keyword == "id_stability" for violation in result.violations)


class TestIdStabilityHeuristic:
    @pytest.mark.parametrize(
        "derived", ["position_time_graph", "cc_position_time_graph", "c_position_time_graph"]
    )
    def test_name_derived_formats_are_flagged(self, concept_record, derived):
        bad = dict(concept_record)
        bad["name"] = "Position Time Graph"
        bad["concept_id"] = derived
        violations = check_id_stability(bad, index=3)
        assert violations
        assert all(violation.keyword == "id_stability" for violation in violations)
        assert violations[0].path == "/3/concept_id"
        assert "derived from the display name" in violations[0].message

    def test_spaces_replaced_form_trips_both_heuristics(self, concept_record):
        bad = dict(concept_record)
        bad["name"] = "Chemical Equilibrium"
        bad["concept_id"] = "chemical_equilibrium"
        violations = check_id_stability(bad, index=2)
        assert len(violations) == 2
        assert {violation.path for violation in violations} == {"/2/concept_id"}
        assert "spaces replaced" in violations[1].message

    def test_hash_derived_id_is_not_flagged(self, concept_record):
        assert check_id_stability(concept_record) == []
        assert check_id_stability({}) == []


class TestQuestionRecordContract:
    def test_valid_question_passes(self):
        result = validate_question_record(make_question())
        assert result.ok
        assert result.checked == 1

    def test_incomplete_question_reports_every_gap(self):
        result = validate_question_record({"question_id": "q1", "text": "hi"})
        assert not result.ok
        assert {violation.keyword for violation in result.violations} == {
            "required",
            "additionalProperties",
        }

    @pytest.mark.parametrize(
        "overrides, keyword, path",
        [
            ({"question_type": "weird"}, "enum", "/question_type"),
            ({"prompt": ""}, "minLength", "/prompt"),
            ({"status": "published"}, "enum", "/status"),
            ({"assesses": []}, "minItems", "/assesses"),
            (
                {"assesses": [{"concept_id": "cc_1", "weight": 0, "role": "primary"}]},
                "exclusiveMinimum",
                "/assesses[0]/weight",
            ),
            (
                {"assesses": [{"concept_id": "cc_1", "weight": 1.5}]},
                "maximum",
                "/assesses[0]/weight",
            ),
            ({"assesses": [{"weight": 1.0}]}, "required", "/assesses[0]/concept_id"),
            ({"difficulty": 2}, "maximum", "/difficulty"),
            ({"bogus": True}, "additionalProperties", "/bogus"),
        ],
    )
    def test_violation_keyword_and_path(self, overrides, keyword, path):
        result = validate_question_record(make_question(**overrides))
        assert not result.ok
        assert any(
            violation.keyword == keyword and violation.path == path
            for violation in result.violations
        ), result.messages()


class TestUnsupportedAndPatternKeywords:
    def test_unsupported_keywords_are_reported_not_dropped(self):
        result = validate_against_schema(
            {},
            {"type": "object", "format": "date", "patternProperties": {"^x": {"type": "string"}}},
            schema_name="probe",
        )
        assert result.ok  # no *implemented* rule was violated ...
        assert result.unsupported_keywords == {"format", "patternProperties"}  # ... and said so

    def test_fully_supported_schema_reports_nothing(self):
        result = validate_against_schema(
            {"a": 1},
            {"type": "object", "properties": {"a": {"type": "integer"}}},
            schema_name="probe",
        )
        assert result.ok
        assert result.unsupported_keywords == set()

    def test_pattern_is_enforced_by_the_hand_rolled_validator(self):
        schema = {
            "type": "object",
            "properties": {"concept_id": {"type": "string", "pattern": "^cc_[0-9a-f]+$"}},
        }
        bad = validate_against_schema({"concept_id": "nope"}, schema, schema_name="probe")
        assert any(violation.keyword == "pattern" for violation in bad.violations)
        good = validate_against_schema({"concept_id": "cc_ab12"}, schema, schema_name="probe")
        assert good.ok


class TestOptionalJsonschemaCrossCheck:
    def test_hand_rolled_verdict_matches_jsonschema(self, concept_record):
        pytest.importorskip("jsonschema")
        schema = load_contract_schema(CONCEPT_SCHEMA_NAME)

        good = validate_with_jsonschema(concept_record, schema, schema_name="concept")
        assert good["available"] is True
        assert good["valid"] is True
        assert good["errors"] == []
        assert validate_concept_record(concept_record).ok is True

        bad = dict(concept_record)
        bad.pop("status")
        bad["extra_field"] = 1
        cross = validate_with_jsonschema(bad, schema, schema_name="concept")
        assert cross["available"] is True
        assert cross["valid"] is False
        assert len(cross["errors"]) == 2  # one missing required + one unexpected
        assert validate_concept_record(bad).ok is False

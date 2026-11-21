"""LearnSense Person 3 — Integration Contracts and Schema Validation Helpers.

Loads and enforces canonical JSON Schema contracts (Draft 2020-12) across integration boundaries:
- Assessment attempts (attempt_schema.json)
- Concepts and Knowledge Graph (concept_schema.json)
- Question Bank items and projections (question_schema.json)
- Learner state snapshots (learner_state_schema.json)
- Learning recommendations (recommendation_schema.json)
- Tutoring requests and responses (tutoring_request_schema.json, tutoring_response_schema.json)
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import jsonschema
from jsonschema import Draft202012Validator

CONTRACTS_DIR = Path(__file__).resolve().parent.parent.parent / "contracts"


class ContractValidatorRegistry:
    """Registry of pre-compiled Draft 2020-12 validators for all shared contracts."""

    _validators: Dict[str, Draft202012Validator] = {}

    @classmethod
    def get_validator(cls, schema_filename: str) -> Draft202012Validator:
        if schema_filename not in cls._validators:
            schema_path = CONTRACTS_DIR / schema_filename
            if not schema_path.is_file():
                raise FileNotFoundError(f"Contract schema not found: {schema_path}")
            with open(schema_path, "r", encoding="utf-8") as f:
                schema_dict = json.load(f)
            cls._validators[schema_filename] = Draft202012Validator(schema_dict)
        return cls._validators[schema_filename]


def validate_contract_payload(schema_filename: str, payload: Dict[str, Any]) -> Tuple[bool, List[str]]:
    """Validates an arbitrary payload against the specified schema file.
    
    Returns:
        (is_valid: bool, error_messages: List[str])
    """
    validator = ContractValidatorRegistry.get_validator(schema_filename)
    errors = sorted(validator.iter_errors(payload), key=lambda e: e.path)
    if errors:
        return False, [f"{'/'.join(str(p) for p in err.path)}: {err.message}" for err in errors]
    return True, []


def validate_attempt(payload: Dict[str, Any]) -> Tuple[bool, List[str]]:
    return validate_contract_payload("attempt_schema.json", payload)


def validate_concept(payload: Dict[str, Any]) -> Tuple[bool, List[str]]:
    return validate_contract_payload("concept_schema.json", payload)


def validate_question(payload: Dict[str, Any]) -> Tuple[bool, List[str]]:
    return validate_contract_payload("question_schema.json", payload)


def validate_learner_state(payload: Dict[str, Any]) -> Tuple[bool, List[str]]:
    return validate_contract_payload("learner_state_schema.json", payload)


def validate_recommendation(payload: Dict[str, Any]) -> Tuple[bool, List[str]]:
    return validate_contract_payload("recommendation_schema.json", payload)


def validate_tutoring_request(payload: Dict[str, Any]) -> Tuple[bool, List[str]]:
    return validate_contract_payload("tutoring_request_schema.json", payload)


def validate_tutoring_response(payload: Dict[str, Any]) -> Tuple[bool, List[str]]:
    return validate_contract_payload("tutoring_response_schema.json", payload)

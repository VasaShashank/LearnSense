"""
Validation against the proposed shared contracts (Person 2).

The team's ``References/LearnSense_Shared_Contracts_v0_1/`` folder ships a
``concept_schema.json`` and a ``question_schema.json`` in JSON Schema
draft 2020-12.  They are marked *proposed_review_required* upstream, so this
module treats them as a proposal to conform to and to report deviations against
-- see ``docs/curriculum/CONTRACT_REVIEW.md`` -- rather than as an authority that
the curriculum package silently rewrites itself around.

Two ways to validate
--------------------

1. **Hand-rolled validator (default, no third-party dependency).**
   ``validate_concept_record()`` / ``validate_question_record()`` implement the
   keyword subset those two schemas actually use.  The subset is listed in
   :data:`SUPPORTED_KEYWORDS`; any other keyword found in a loaded schema is
   surfaced in the result's ``unsupported_keywords`` so a caller is never told
   "valid" when the validator simply skipped the rule that would have failed.

2. **The ``jsonschema`` package (optional).**
   ``jsonschema`` is installed in this environment but is *not* a declared
   requirement of the project, so nothing in the runtime path imports it.
   Tests may cross-check the hand-rolled result against it via
   :func:`validate_with_jsonschema`.

Schema resolution
-----------------

Schemas are not vendored into this repository (``References/`` is read-only
reference material).  :func:`load_contract_schema` looks in, in order:

1. ``$LEARNSENSE_CONTRACT_DIR``,
2. ``<repo>/contracts/schemas`` (a local copy, if one is ever added),
3. ``<repo>/../References/LearnSense_Shared_Contracts_v0_1/schemas``.

If none exists, :class:`ContractSchemaNotFoundError` explains exactly what to do
instead of validating against a guess of what the contract says.

Beyond JSON Schema
------------------

Schema conformance does not prove the *semantics* the contract's description
line asks for -- "IDs must be stable and must not be derived from display
names".  :func:`validate_reference_integrity` and :func:`check_id_stability`
cover the checks a schema cannot express: dangling ``prerequisite_concept_ids``,
``assesses`` entries pointing at concepts that do not exist, and concept ids
that were (wrongly) derived from a display name.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set

__all__ = [
    "CONCEPT_SCHEMA_NAME",
    "ContractSchemaNotFoundError",
    "ContractValidationResult",
    "ContractViolation",
    "QUESTION_SCHEMA_NAME",
    "SUPPORTED_KEYWORDS",
    "check_id_stability",
    "load_contract_schema",
    "validate_against_schema",
    "validate_concept_graph",
    "validate_concept_record",
    "validate_question_record",
    "validate_reference_integrity",
    "validate_with_jsonschema",
]

CONCEPT_SCHEMA_NAME = "concept_schema.json"
QUESTION_SCHEMA_NAME = "question_schema.json"

#: JSON Schema keywords this module implements.  Anything else in a schema is
#: reported as ``unsupported`` rather than silently ignored.
SUPPORTED_KEYWORDS = frozenset(
    {
        "$schema",
        "$id",
        "title",
        "description",
        "default",
        "type",
        "enum",
        "required",
        "properties",
        "additionalProperties",
        "items",
        "minItems",
        "maxItems",
        "uniqueItems",
        "minLength",
        "maxLength",
        "minimum",
        "maximum",
        "exclusiveMinimum",
        "exclusiveMaximum",
        "pattern",
        "examples",
    }
)

# Keywords that are pure annotation and need no enforcement behaviour.
_ANNOTATION_KEYWORDS = frozenset(
    {"$schema", "$id", "title", "description", "default", "examples"}
)


class ContractSchemaNotFoundError(FileNotFoundError):
    """Raised when a shared-contract schema file cannot be located."""


@dataclass(frozen=True)
class ContractViolation:
    """One reason an instance does not conform to a contract."""

    path: str
    keyword: str
    message: str
    expected: Any = None
    got: Any = None

    def as_dict(self) -> Dict[str, Any]:
        return {
            "path": self.path,
            "keyword": self.keyword,
            "message": self.message,
            "expected": self.expected,
            "got": self.got,
        }

    def __str__(self) -> str:  # pragma: no cover - formatting only
        location = self.path or "<root>"
        return f"{location}: {self.message}"


@dataclass
class ContractValidationResult:
    """Outcome of validating one or more instances against one schema."""

    schema_name: str
    schema_source: str
    violations: List[ContractViolation] = field(default_factory=list)
    unsupported_keywords: Set[str] = field(default_factory=set)
    checked: int = 0

    @property
    def ok(self) -> bool:
        return not self.violations

    @property
    def valid(self) -> bool:
        """Alias of :attr:`ok`, kept so callers can read either way."""
        return self.ok

    @property
    def error_count(self) -> int:
        return len(self.violations)

    def messages(self) -> List[str]:
        return [str(violation) for violation in self.violations]

    def as_dict(self) -> Dict[str, Any]:
        return {
            "schema_name": self.schema_name,
            "schema_source": self.schema_source,
            "ok": self.ok,
            "checked": self.checked,
            "error_count": self.error_count,
            "violations": [violation.as_dict() for violation in self.violations],
            "unsupported_keywords": sorted(self.unsupported_keywords),
        }

    def raise_if_invalid(self) -> None:
        if self.violations:
            preview = "; ".join(self.messages()[:5])
            more = "" if len(self.violations) <= 5 else f" (+{len(self.violations) - 5} more)"
            raise ValueError(
                f"{self.schema_name}: {self.error_count} contract violation(s): {preview}{more}"
            )


# ------------------------------------------------------------------ schema IO


def _candidate_dirs() -> List[Path]:
    here = Path(__file__).resolve()
    repo_root = here.parents[1]
    candidates: List[Path] = []
    env_dir = os.environ.get("LEARNSENSE_CONTRACT_DIR")
    if env_dir:
        candidates.append(Path(env_dir))
    candidates.append(repo_root / "contracts" / "schemas")
    candidates.append(
        repo_root.parent / "References" / "LearnSense_Shared_Contracts_v0_1" / "schemas"
    )
    return candidates


def contract_schema_paths() -> Dict[str, Optional[Path]]:
    """Where each known contract schema was (or would be) loaded from."""
    return {
        name: next(
            (directory / name for directory in _candidate_dirs() if (directory / name).exists()),
            None,
        )
        for name in (CONCEPT_SCHEMA_NAME, QUESTION_SCHEMA_NAME)
    }


def load_contract_schema(name: str) -> Dict[str, Any]:
    """
    Load a shared-contract schema by file name.

    Raises :class:`ContractSchemaNotFoundError` with the search path when the
    file is unavailable, rather than falling back to a hand-maintained copy that
    could drift from the reference.
    """
    if not name.endswith(".json"):
        name = f"{name}.json"
    searched: List[str] = []
    for directory in _candidate_dirs():
        path = directory / name
        searched.append(str(path))
        if path.exists():
            with open(path, "r", encoding="utf-8") as handle:
                return json.load(handle)
    raise ContractSchemaNotFoundError(
        f"Shared contract schema '{name}' not found. Searched: {searched}. "
        f"Set LEARNSENSE_CONTRACT_DIR to the directory holding "
        f"LearnSense_Shared_Contracts_v0_1/schemas, or copy the schema into "
        f"<repo>/contracts/schemas."
    )


# --------------------------------------------------------------- the validator


def _type_ok(value: Any, expected: Any) -> bool:
    if expected == "null":
        return value is None
    if expected == "boolean":
        return isinstance(value, bool)
    if expected == "integer":
        # bool is a subclass of int in Python; it must not satisfy "integer".
        return isinstance(value, int) and not isinstance(value, bool)
    if expected == "number":
        return (isinstance(value, (int, float)) and not isinstance(value, bool)) or (
            isinstance(value, float)
        )
    if expected == "string":
        return isinstance(value, str)
    if expected == "array":
        return isinstance(value, (list, tuple))
    if expected == "object":
        return isinstance(value, dict)
    if expected == "null":
        return value is None
    return False


def _types_ok(value: Any, expected: Any) -> bool:
    if isinstance(expected, list):
        return any(_type_ok(value, item) for item in expected)
    return _type_ok(value, expected)


def _json_path(parts: Sequence[Any]) -> str:
    out = ""
    for part in parts:
        if isinstance(part, int):
            out += f"[{part}]"
        else:
            out += f"/{part}"
    return out or "/"


def _collect_unsupported(schema: Any, found: Set[str]) -> None:
    if not isinstance(schema, dict):
        return
    for key, value in schema.items():
        if key not in SUPPORTED_KEYWORDS and key not in _ANNOTATION_KEYWORDS:
            found.add(key)
        if key in {"properties", "patternProperties"} and isinstance(value, dict):
            for subschema in value.values():
                _collect_unsupported(subschema, found)
        elif key in {"items", "additionalProperties", "contains", "not"}:
            if isinstance(value, dict):
                _collect_unsupported(value, found)
        elif key in {"allOf", "anyOf", "oneOf", "prefixItems"} and isinstance(value, list):
            for subschema in value:
                _collect_unsupported(subschema, found)


def _hashable(value: Any) -> Any:
    """Make a value comparable for ``uniqueItems`` without losing meaning."""
    if isinstance(value, dict):
        return ("object", tuple(sorted((k, _hashable(v)) for k, v in value.items())))
    if isinstance(value, (list, tuple)):
        return ("array", tuple(_hashable(v) for v in value))
    if isinstance(value, bool):
        return ("boolean", value)
    if value is None:
        return ("null",)
    if isinstance(value, (int, float)):
        return ("number", float(value))
    return (type(value).__name__, value)


def validate_against_schema(
    instance: Any, schema: Dict[str, Any], *, schema_name: str = "schema", schema_source: str = ""
) -> ContractValidationResult:
    """
    Validate ``instance`` against ``schema`` using the implemented keyword subset.

    Unknown keywords are collected into the returned result's
    ``unsupported_keywords``: an "ok" result whose schema also contains
    unsupported keywords must be read as "no implemented rule was violated",
    not as "fully conformant".
    """
    unsupported: Set[str] = set()
    _collect_unsupported(schema, unsupported)
    violations: List[ContractViolation] = []
    _validate_node(instance, schema, (), violations)
    return ContractValidationResult(
        schema_name=schema_name,
        schema_source=schema_source,
        violations=violations,
        unsupported_keywords=unsupported,
        checked=1,
    )


def _validate_node(
    value: Any,
    schema: Dict[str, Any],
    path: Sequence[Any],
    violations: List[ContractViolation],
) -> None:
    if not isinstance(schema, dict):
        return

    if "type" in schema and not _types_ok(value, schema["type"]):
        violations.append(
            ContractViolation(
                path=_json_path(path),
                keyword="type",
                message=f"expected type {schema['type']!r}",
                expected=schema["type"],
                got=type(value).__name__,
            )
        )
        # Further keyword checks assume the right shape; stop here.
        return

    if "enum" in schema:
        allowed = schema["enum"]
        if not any(_equal(value, candidate) for candidate in allowed):
            violations.append(
                ContractViolation(
                    path=_json_path(path),
                    keyword="enum",
                    message=f"value not in {allowed!r}",
                    expected=allowed,
                    got=value,
                )
            )

    if isinstance(value, str) and "minLength" in schema and len(value) < schema["minLength"]:
        violations.append(
            ContractViolation(
                path=_json_path(path),
                keyword="minLength",
                message=f"shorter than minLength {schema['minLength']}",
                expected=schema["minLength"],
                got=len(value),
            )
        )
    if isinstance(value, str) and "maxLength" in schema and len(value) > schema["maxLength"]:
        violations.append(
            ContractViolation(
                path=_json_path(path),
                keyword="maxLength",
                message=f"longer than maxLength {schema['maxLength']}",
                expected=schema["maxLength"],
                got=len(value),
            )
        )
    if isinstance(value, str) and "pattern" in schema:
        import re

        if not re.search(schema["pattern"], value):
            violations.append(
                ContractViolation(
                    path=_json_path(path),
                    keyword="pattern",
                    message=f"value does not match pattern {schema['pattern']!r}",
                    expected=schema["pattern"],
                    got=value,
                )
            )

    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if "minimum" in schema and value < schema["minimum"]:
            violations.append(
                ContractViolation(
                    path=_json_path(path),
                    keyword="minimum",
                    message=f"below minimum {schema['minimum']}",
                    expected=schema["minimum"],
                    got=value,
                )
            )
        if "maximum" in schema and value > schema["maximum"]:
            violations.append(
                ContractViolation(
                    path=_json_path(path),
                    keyword="maximum",
                    message=f"above maximum {schema['maximum']}",
                    expected=schema["maximum"],
                    got=value,
                )
            )
        if "exclusiveMinimum" in schema and value <= schema["exclusiveMinimum"]:
            violations.append(
                ContractViolation(
                    path=_json_path(path),
                    keyword="exclusiveMinimum",
                    message=f"not above exclusiveMinimum {schema['exclusiveMinimum']}",
                    expected=schema["exclusiveMinimum"],
                    got=value,
                )
            )
        if "exclusiveMaximum" in schema and value >= schema["exclusiveMaximum"]:
            violations.append(
                ContractViolation(
                    path=_json_path(path),
                    keyword="exclusiveMaximum",
                    message=f"not below exclusiveMaximum {schema['exclusiveMaximum']}",
                    expected=schema["exclusiveMaximum"],
                    got=value,
                )
            )

    if isinstance(value, (list, tuple)):
        if "minItems" in schema and len(value) < schema["minItems"]:
            violations.append(
                ContractViolation(
                    path=_json_path(path),
                    keyword="minItems",
                    message=f"fewer than minItems {schema['minItems']}",
                    expected=schema["minItems"],
                    got=len(value),
                )
            )
        if "maxItems" in schema and len(value) > schema["maxItems"]:
            violations.append(
                ContractViolation(
                    path=_json_path(path),
                    keyword="maxItems",
                    message=f"more than maxItems {schema['maxItems']}",
                    expected=schema["maxItems"],
                    got=len(value),
                )
            )
        if schema.get("uniqueItems"):
            seen: Dict[Any, int] = {}
            for index, item in enumerate(value):
                key = _hashable(item)
                if key in seen:
                    violations.append(
                        ContractViolation(
                            path=_json_path(list(path) + [index]),
                            keyword="uniqueItems",
                            message=f"duplicates item at index {seen[key]}",
                            expected="unique items",
                            got=item,
                        )
                    )
                else:
                    seen[key] = index
        item_schema = schema.get("items")
        if isinstance(item_schema, dict):
            for index, item in enumerate(value):
                _validate_node(item, item_schema, list(path) + [index], violations)

    if isinstance(value, dict):
        for key in schema.get("required", []) or []:
            if key not in value:
                violations.append(
                    ContractViolation(
                        path=_json_path(list(path) + [key]),
                        keyword="required",
                        message=f"required property '{key}' is missing",
                        expected=key,
                        got=None,
                    )
                )
        properties = schema.get("properties") or {}
        for key, subvalue in value.items():
            if key in properties:
                _validate_node(subvalue, properties[key], list(path) + [key], violations)
                continue
            extra = schema.get("additionalProperties")
            if extra is False:
                violations.append(
                    ContractViolation(
                        path=_json_path(list(path) + [key]),
                        keyword="additionalProperties",
                        message=f"unexpected property '{key}'",
                        expected=sorted(properties),
                        got=key,
                    )
                )
            elif isinstance(extra, dict):
                _validate_node(subvalue, extra, list(path) + [key], violations)


def _equal(left: Any, right: Any) -> bool:
    """Enum comparison that does not let ``True == 1`` slip through."""
    if isinstance(left, bool) != isinstance(right, bool):
        return False
    if isinstance(left, bool) and isinstance(right, bool):
        return left is right
    return left == right


# ------------------------------------------------------------- convenience API


def validate_concept_record(record: Dict[str, Any]) -> ContractValidationResult:
    """Validate one canonical concept against the proposed ``concept_schema.json``."""
    schema = load_contract_schema(CONCEPT_SCHEMA_NAME)
    result = validate_against_schema(
        record,
        schema,
        schema_name=CONCEPT_SCHEMA_NAME,
        schema_source=str(contract_schema_paths()[CONCEPT_SCHEMA_NAME]),
    )
    result.checked = 1
    return result


def validate_question_record(record: Dict[str, Any]) -> ContractValidationResult:
    """Validate one question record against the proposed ``question_schema.json``."""
    schema = load_contract_schema(QUESTION_SCHEMA_NAME)
    result = validate_against_schema(
        record,
        schema,
        schema_name=QUESTION_SCHEMA_NAME,
        schema_source=str(contract_schema_paths()[QUESTION_SCHEMA_NAME]),
    )
    result.checked = 1
    return result


def validate_concept_graph(graph: Any) -> ContractValidationResult:
    """
    Validate every concept of a ``CurriculumGraph`` against the concept contract.

    Adds two non-schema checks that matter to consumers of the export: duplicate
    concept ids in the export, and duplicate ``source_id`` values within one
    concept's evidence list (which would make provenance ambiguous).
    """
    records = [
        graph.concepts[concept_id].to_contract_record() for concept_id in graph.concept_ids()
    ]
    schema = load_contract_schema(CONCEPT_SCHEMA_NAME)
    source = str(contract_schema_paths()[CONCEPT_SCHEMA_NAME])
    result = ContractValidationResult(
        schema_name=CONCEPT_SCHEMA_NAME,
        schema_source=source,
        checked=len(records),
    )
    for index, record in enumerate(records):
        # The contract's root is an object, so records are validated one by one;
        # their paths are prefixed with the record index to stay locatable.
        record_result = validate_against_schema(
            record, schema, schema_name=CONCEPT_SCHEMA_NAME, schema_source=source
        )
        for violation in record_result.violations:
            result.violations.append(
                ContractViolation(
                    path=f"/{index}{violation.path if violation.path != '/' else ''}",
                    keyword=violation.keyword,
                    message=violation.message,
                    expected=violation.expected,
                    got=violation.got,
                )
            )
        result.unsupported_keywords.update(record_result.unsupported_keywords)

    seen: Dict[str, int] = {}
    for index, record in enumerate(records):
        concept_id = record.get("concept_id")
        if concept_id in seen:
            result.violations.append(
                ContractViolation(
                    path=f"/{index}/concept_id",
                    keyword="duplicate_id",
                    message=f"concept_id '{concept_id}' also used by record {seen[concept_id]}",
                    expected="unique concept ids",
                    got=concept_id,
                )
            )
        else:
            seen[concept_id] = index
        source_ids = [ref.get("source_id") for ref in record.get("source_refs") or []]
        if len(source_ids) != len(set(source_ids)):
            result.violations.append(
                ContractViolation(
                    path=f"/{index}/source_refs",
                    keyword="duplicate_source",
                    message="duplicate source_id within one concept's source_refs",
                    expected="unique source_ids",
                    got=source_ids,
                )
            )
    return result


def validate_reference_integrity(
    records: Iterable[Dict[str, Any]],
    *,
    known_concept_ids: Optional[Set[str]] = None,
    schema_name: str = CONCEPT_SCHEMA_NAME,
) -> ContractValidationResult:
    """
    Dangling-reference checks a JSON Schema cannot express.

    Every ``prerequisite_concept_ids`` entry must resolve to a concept in
    ``known_concept_ids`` (or, when that is ``None``, to one of the supplied
    records).  Concept ids must be non-empty and must not be derived from the
    display name -- the contract's own description requires stability, and a
    slug of ``name`` breaks the moment someone renames a concept, so it is
    flagged here as a warning-level violation.
    """
    records = list(records)
    if known_concept_ids is None:
        known_concept_ids = {str(record.get("concept_id")) for record in records}
    violations: List[ContractViolation] = []
    for index, record in enumerate(records):
        for position, prereq in enumerate(record.get("prerequisite_concept_ids") or []):
            if prereq not in known_concept_ids:
                violations.append(
                    ContractViolation(
                        path=f"/{index}/prerequisite_concept_ids/{position}",
                        keyword="reference_integrity",
                        message=f"prerequisite '{prereq}' is not a known concept id",
                        expected="a known concept id",
                        got=prereq,
                    )
                )
        violations.extend(check_id_stability(record, index=index))
    return ContractValidationResult(
        schema_name=schema_name,
        schema_source=str(contract_schema_paths().get(schema_name) or "records"),
        violations=violations,
        unsupported_keywords=set(),
        checked=len(records),
    )


def check_id_stability(record: Dict[str, Any], *, index: int = 0) -> List[ContractViolation]:
    """
    Flag concept ids that look derived from the display name.

    This is a heuristic, and it says so: it catches ``cc_position_time_graph``
    style ids and id/name pairs that differ only by slugification.  It cannot
    prove a hash-derived id is stable, it can only catch the obvious violation
    of the contract's "must not be derived from display names" rule.
    """
    concept_id = str(record.get("concept_id") or "")
    name = str(record.get("name") or "")
    if not concept_id:
        return []
    violations: List[ContractViolation] = []
    from curriculum.ids import slugify

    name_slug = slugify(name)
    if name_slug and concept_id.lower() in {name_slug, f"cc_{name_slug}", f"c_{name_slug}"}:
        violations.append(
            ContractViolation(
                path=f"/{index}/concept_id",
                keyword="id_stability",
                message=(
                    "concept_id appears to be derived from the display name; "
                    "renaming the concept would orphan every stored reference"
                ),
                expected="an id independent of the display name",
                got=concept_id,
            )
        )
    if name and concept_id.lower() == name.lower().replace(" ", "_"):
        violations.append(
            ContractViolation(
                path=f"/{index}/concept_id",
                keyword="id_stability",
                message="concept_id is the display name with spaces replaced",
                expected="an id independent of the display name",
                got=concept_id,
            )
        )
    return violations


def validate_with_jsonschema(
    instance: Any, schema: Dict[str, Any], *, schema_name: str = "schema"
) -> Dict[str, Any]:
    """
    Cross-check an instance with the optional ``jsonschema`` package.

    Only used to corroborate the hand-rolled validator in tests; the runtime
    path never depends on it.  Returns ``{"available": False, ...}`` when the
    package is absent instead of pretending the check passed.
    """
    try:
        import jsonschema
    except ImportError:
        return {
            "available": False,
            "schema_name": schema_name,
            "reason": "jsonschema is not installed",
        }
    validator_cls = jsonschema.validators.validator_for(schema, default=jsonschema.Draft202012Validator)
    validator = validator_cls(schema)
    errors = sorted(validator.iter_errors(instance), key=lambda error: list(error.absolute_path))
    return {
        "available": True,
        "schema_name": schema_name,
        "valid": not errors,
        "errors": [
            {
                "path": "/" + "/".join(str(part) for part in error.absolute_path),
                "message": error.message,
            }
            for error in errors
        ],
    }

# Shared-contract review notes (Person 2)

Open questions and deviations for the owners of the shared LearnSense
contracts, collected while implementing the curriculum/concept export. Nothing
in `References/` was modified or copied wholesale; the schemas are read-only
inputs.

**Sources reviewed**

* `References/LearnSense_Shared_Contracts_v0_1/schemas/concept_schema.json`
* `References/LearnSense_Shared_Contracts_v0_1/schemas/question_schema.json`

**Implementation under review**

* `curriculum/contract.py` — schema resolution, subset validator, export/round-trip
* `curriculum/seed.py` / `backend/routes/curriculum.py` — `GET /api/curriculum/contract`
* Pinned by 43 tests in `tests/unit/curriculum/test_contract_compat.py`

---

## 1. Schema location (deviation: sibling directory, resolution order)

The schemas do not live in this repository. `contract_schema_paths()` resolves
in this order:

1. `$LEARNSENSE_CONTRACT_DIR`
2. `<repo>/contracts/schemas`
3. `<repo>/../References/LearnSense_Shared_Contracts_v0_1/schemas` (the sibling
   `References/` checkout)

A missing schema raises `ContractSchemaNotFoundError` that lists every location
searched; there is no silent fallback to a hand-written copy.

**Question for contract owners:** should the canonical schemas be vendored into
this repository at a pinned version (`contracts/schemas/`), so the API export
cannot break when the `References/` checkout moves?

## 2. `concept_schema.json` is treated as a proposal

The runtime export does not depend on `jsonschema` being installed:

* `to_contract_record()` emits exactly the schema's 10 properties
  (`concept_id`, `name`, `description`, `status`, plus `metadata`,
  `prerequisite_concept_ids`, `source_refs`, …) with
  `additionalProperties: false` honoured;
* `from_contract_record()` round-trips losslessly (tests assert record equality
  after a full cycle);
* a hand-rolled subset validator is the authoritative pass/fail path;
* when `jsonschema` **is** installed, `validate_with_jsonschema()` runs as a
  cross-check and its verdict/errors are reported alongside — it never changes
  the result.

**Question:** is the 10-property set stable enough to become a required
dependency, or should it remain a proposal as assumed here?

## 3. Violation path syntax (deviation from some JSON-Pointer conventions)

Our `ContractViolation.path` values use bracket indices and, for `required`,
include the missing property name:

| Case | Path | Notes |
| --- | --- | --- |
| array element scalar | `/assesses[0]/weight` | |
| `uniqueItems` duplicate | `/tags[1]` | points at the **duplicate** element, not the first occurrence |
| nested object missing key | `/source_refs[1]/source_id` | `required` names the property in `message`/`expected` |
| `additionalProperties` | `/extra_field` | the unexpected property itself |
| reference integrity | `/0/prerequisite_concept_ids/0` | |

**Question:** do downstream consumers expect JSON Pointer with `-` array
suffixes (`/assesses/0/weight`) instead? If so, we will add a formatter rather
than change recorded paths.

## 4. Unsupported schema keywords are reported, not fatal

The schemas use `format` and `patternProperties`, which the subset validator
does not interpret. Validation results carry `unsupported_keywords`
(`{"format", "patternProperties"}`) while `ok` stays `True`; `pattern` **is**
enforced.

**Question:** should `format` be enforced (which formats are required to
validate — `date-time`, `uri`, …)? Today's verdict deliberately ignores it, so
two conforming implementations can disagree on the same record.

## 5. `question_schema.json` / `assesses` weights (precision question)

The simulator bridge exports `assesses` entries whose weights are normalised to
sum to exactly `1.0`: two-way splits become `0.7/0.3`, three-way splits
`0.7/0.15/0.15` (rounded, then adjusted to keep the sum exact).

**Question:** does the contract require `weights == 1.0` per question, and what
rounding is acceptable? Current behaviour guarantees the sum and documents the
split policy.

## 6. Provenance of mapped concepts

Simulator concept ids are never adopted as canonical ids; the mapping table
(simulator row -> canonical `cc_…` id, with an explicit override field) is the
record of correspondence, and overrides pointing at unknown canonical ids are
refused with an error.

**Question:** should `source_refs[]` additionally carry the simulator row id so
a mapped concept's origin is queryable from the contract record alone? The
field exists and we populate it for document-sourced concepts; simulator-sourced
mappings currently rely on the stored mapping run.

## 7. No deviations found in these areas (recorded for completeness)

* `status` enum `draft | active | deprecated` matches
  `curriculum.models.ConceptLifecycleStatus` exactly.
* `concept_id`/`name`/`description` required set matches our model's required
  fields; stable-id format (`cc_<16 hex>`) passes the schema's `pattern`.
* `prerequisite_concept_ids` entries are validated against the live graph
  (dangling references are violations, reported per index).

## Test evidence

```
python -m pytest tests/unit/curriculum/test_contract_compat.py -q   # 43 passed
```

Covering: schema resolution order and error message, record shape == schema
properties, round-trip, required/unexpected/uniqueItems/nested/duplicate-id
violations and their exact paths, reference integrity (with and without an
explicit known-id set), id-stability heuristic (rejects display-name-derived
ids, accepts hash ids), question-record violations, unsupported-keyword
reporting, and the `jsonschema` cross-check.

# Curriculum & Knowledge Graph (Person 2)

This directory documents the Person 2 workstream: the canonical concept graph,
deterministic content-to-concept mapping, curriculum seeding/versioning/review,
provenance, simulator bridging, and the evaluation harness that measures all of
it.

**Owned code:** the top-level `curriculum/` package, `evaluation/curriculum_eval.py`,
`backend/routes/curriculum.py`, `backend/services/curriculum_service.py`, the
router mount in `backend/app.py`, `tests/unit/curriculum/`, `tests/fixtures/curriculum/`
and `tests/integration/test_curriculum_api.py`.

**Out of scope (other workstreams):** auth/tenancy/persistence (Person 1),
BKT/grading/mastery (Person 3), frontend visualisation (Person 4), ingestion/OCR
operations (Person 5). The Phase 1 ingestion -> `StructuredDocument` boundary is
preserved untouched; nothing in `curriculum/` parses PDFs or calls an LLM.

---

## Package map

| Module | Responsibility |
| --- | --- |
| `curriculum/ids.py` | Stable id derivation (see below), `excerpt_hash` for source refs |
| `curriculum/models.py` | `CanonicalConcept`, `ConceptRelationship`, `SourceRef`, `AuditInfo`; `content_dict()` (audit timestamps excluded) |
| `curriculum/normalization.py` | Deterministic term normalization (typographic folds: en-dash, U+2212 minus, hyphens) and tokenization for matching |
| `curriculum/graph.py` | `CurriculumGraph`, `CurriculumGraphValidator`, `PrerequisiteCycleError`, issue codes |
| `curriculum/review.py` | `CurriculumReviewService`: accept / reject / merge / deprecate / replace / relationship status; `ReviewConflictError`; id-map writes |
| `curriculum/versioning.py` | Content-addressed snapshots, `diff_graphs` |
| `curriculum/repository.py` | JSON persistence under `storage/curriculum/` (atomic writes) |
| `curriculum/provenance.py` | Append-only provenance ledger with stage-addressed record ids; coverage metrics |
| `curriculum/mapping.py` | Deterministic mapper: rules R1-R5, statuses ACCEPTED/UNCERTAIN/UNMAPPED, `ProposedConcept`, `ContentMappingResult` |
| `curriculum/seed.py` | `CurriculumSpec` -> graph (deterministic, validated, history-preserving) |
| `curriculum/simulator.py` | Read-only bridge from the JEE simulator CSV; mapping/override, prerequisite audit, contract `assesses` export |
| `curriculum/contract.py` | Shared-contract schema resolution + subset validator (+ optional `jsonschema` cross-check) |
| `curriculum/quality.py` | Structural quality report (provenance coverage, graph statistics) |
| `curriculum/adapters.py` | One-way projection of the canonical graph into the read-only view types Person 3/4 already consume (`ConceptView`, `PrerequisiteLink`, `phase2.models.Relationship`); no learner state is written back |
| `evaluation/curriculum_eval.py` | Metric functions: precision/recall/F1, exact match, abstention, recall-answerable, per-item coverage |

## Canonical model and ids

* A **concept** is identified by `concept_id = cc_<sha256(curriculum_id::stable_key)[:16]>`.
  The id is derived from the *stable key*, never from the display name, and is
  **frozen at creation**: renaming, aliasing or re-seeding never changes it.
  Display names and aliases are ordinary editable attributes.
* Phase 2's document-scoped `c_…` extraction ids are **not** canonical. Turning
  one into a canonical concept goes through the review flow (accept with an
  explicit stable key or merge), never by adopting the id.
* Simulator CSV concept ids are **not** canonical either. The bridge produces an
  explicit mapping (or an honest UNMAPPED/AMBIGUOUS verdict) and never writes
  simulator ids into the graph.
* **Relationships** are typed edges with deterministic ids. The prerequisite
  convention is `A --prerequisite_of--> B` ("A must come before B"); B's
  `prerequisite_concept_ids` list contains A. The validator rejects direction
  mismatches in both directions:
  * `PREREQUISITE_DIRECTION_MISMATCH` (ERROR) — edge exists but the target's
    prerequisite list does not back it;
  * `PREREQUISITE_LIST_UNBACKED` (ERROR) — list entry with no live
    (non-rejected) backing edge.
* The graph contains curriculum structure only — no student mastery, no
  learner state.

## Validation policy

`CurriculumGraphValidator` is deterministic and runs with no network access.
The graph is **never auto-repaired**; errors fail the operation that produced
them. `is_valid` means "no ERROR-severity issue"; warnings are reported but do
not invalidate.

ERROR codes (all unit-tested in `tests/unit/curriculum/test_graph_validation.py`):

`DUPLICATE_CONCEPT_NAME`, `DUPLICATE_CONCEPT_ALIAS`,
`ALIAS_COLLIDES_WITH_CANONICAL_NAME`, `MISSING_SOURCE_CONCEPT`,
`MISSING_TARGET_CONCEPT`, `SELF_LOOP` (edge and prerequisite list),
`DUPLICATE_RELATIONSHIP`, `MISSING_PREREQUISITE_CONCEPT`,
`PREREQUISITE_LIST_UNBACKED`, `PREREQUISITE_DIRECTION_MISMATCH`,
`PREREQUISITE_CYCLE`.

Prerequisite **cycles are always rejected**; other edge types (e.g. `part_of`)
may be cyclic.

WARNING codes: `UNSUPPORTED_RELATIONSHIP` (accepted edge with no evidence from
a non-human extraction method), `LOW_CONFIDENCE_PREREQUISITE`,
`EDGE_FROM_DEPRECATED_CONCEPT`, `ORPHAN_CONCEPT` (only when the graph has more
than one active concept).

Human-authored extraction methods — which satisfy evidence requirements on
their own — are `curriculum_review`, `teacher_authored`, `curriculum_spec`
(`CurriculumGraphValidator.HUMAN_AUTHORED_METHODS`).

## Deterministic mapping (content -> concepts)

`match_strength` is a **match-strength score, not a probability and not a
calibrated accuracy**. Its meaning is exactly the rule that produced it:

| Rule | Condition | Kind | Base strength |
| --- | --- | --- | --- |
| R1 | surface == normalized canonical name | `canonical_name` | 1.00 |
| R2 | surface == normalized alias | `alias` | 0.92 |
| R3 | surface on term boundaries inside a name/alias covering >= 60% of its length | `alias` | 0.80 |
| R4 | token Jaccard(surface, name) >= 0.60 | `alias` | 0.60 + 0.30 * jaccard |
| R5 | wording identical after notation stripping, surface contains notation characters | `notation_variant` | 0.75 |

Two documented bonuses apply to *text passages only* (never to extracted
concepts): +0.10 definition position, +0.05 subject context. Strength is
clamped to [0, 1].

Decision thresholds (fixed):

* **ACCEPTED** — best strength >= 0.90 **and** the runner-up is >= 0.05 lower;
* **UNCERTAIN** — best strength >= 0.60 but not decisive;
* **UNMAPPED** — nothing at or above 0.60.

Unmapped content stays unmapped: the mapper never forces every passage onto a
concept. No LLM or paid API participates in normalization, matching or graph
validation.

## Seeding a curriculum

`curriculum/seed.py::seed_curriculum(spec, repository=None, reviewer_id=…, validate=True)`
builds a graph from a `CurriculumSpec`:

* concepts are created sorted by `stable_key`, so any writing order of the same
  spec yields the same fingerprint and ids;
* prerequisites may be declared per concept (`prerequisites`) **and/or** as
  explicit `relationships`; duplicates collapse onto one deterministic edge;
* seeded concepts land `status=active` / `review_status=accepted` with
  SYSTEM-role review records; provenance records are written for every concept
  and relationship;
* validation failures raise `ValueError` (cycle, unknown key, duplicate key,
  self-prerequisite) — nothing half-built is persisted;
* **re-seeding preserves history**: concepts already stored keep their original
  creation identity (`audit.created_at`/`created_by`/`revision`), which is what
  keeps stage-addressed provenance ids idempotent across reseeds (regression
  test: `test_reseed_across_a_clock_boundary_keeps_creation_history`).

## Shared contracts

Contract records follow `References/LearnSense_Shared_Contracts_v0_1/schemas/concept_schema.json`
(read-only reference material, resolved via `LEARNSENSE_CONTRACT_DIR` ->
repo `contracts/schemas` -> the sibling `References/` copy; a missing schema
raises `ContractSchemaNotFoundError` listing where it looked).

* `to_contract_record()` emits exactly the schema's 10 properties;
  `from_contract_record()` round-trips losslessly; `additionalProperties: false`
  is honoured.
* The runtime path is the hand-rolled subset validator in
  `curriculum/contract.py`; `jsonschema`, when installed, is an optional
  cross-check only (it never changes the pass/fail verdict).
* Violation paths use bracket indices: `/assesses[0]/weight`,
  `/tags[1]` (uniqueItems points at the duplicate element), required-property
  failures name the missing property.
* Deviations and questions for the contract owners are tracked in
  [`CONTRACT_REVIEW.md`](CONTRACT_REVIEW.md).

## Simulator bridge

`curriculum/simulator.py` reads the simulator's `concepts.csv`/questions
(read-only input from the shared `References/` archive) and produces:

* per-simulator-concept mapping: exact-name MAPPED (1.0), alias MAPPED (0.92),
  AMBIGUOUS when top candidates are within 0.05 of each other, UNMAPPED with a
  reason — plus optional explicit overrides, which refuse unknown targets;
* `resolve_map()` returning only confident mappings;
* a prerequisite audit (backed / contradicted / unchecked, with denominators);
* contract `assesses` entries for question records (weights sum to 1.0).

The bridge never mutates the graph.

## Evaluation

`evaluation/curriculum_eval.py` defines the metrics; the pilot fixture
`tests/fixtures/curriculum/pilot_dataset.json` doubles as seed spec and gold
reference, split into **pilot** and **held-out** slices:

* primary: end-to-end precision / recall / F1 per split (tp/fp/fn and
  denominators are always reported; `None` when undefined, with
  `undefined_reason`);
* `recall_answerable` — mapping-only recall on items whose gold concept was
  present in the run;
* `exact_match_accuracy`, `abstention_rate`, `status_counts` (restricted to the
  split's annotated items);
* per-item `source_mentions_gold` overrides beat the substring heuristic;
* extraction failures and mapping failures are reported separately;
* expected-count checks (`_check_expected_counts`) report mismatches as flags —
  they never raise.

Measured on the fixture (deterministic; reproduce with
`tests/unit/curriculum/test_evaluation_metrics.py` or the eval script flow):

```
pilot      tp 4  fp 1  fn 0  prec 0.8    rec 1.0    f1 0.8889  exact 0.8333  abstain 0.1667  rec_ans 1.0
held_out   tp 2  fp 0  fn 1  prec 1.0    rec 0.6667 f1 0.8     exact 0.75    abstain 0.5     rec_ans 1.0
relations  tp 8  fp 0  fn 0   direction 7 correct / 0 reversed
aliases    9 merged correctly, 0 split, 0 spurious
13/13 expected-count checks OK
```

These are fixture results with explicit denominators — not accuracy claims
about real-world content.

## HTTP API

28 routes under `/api/curriculum/...` (`backend/routes/curriculum.py`, mounted
in `backend/app.py`; service built per request):

| Group | Routes |
| --- | --- |
| Status & reads | `GET /status`, `GET ""`, `GET /concepts` (filters: subject, class, status, q, include_deprecated, limit/offset), `GET /concepts/{id}`, `GET /concepts/{id}/prerequisites`, `GET /concepts/{id}/closure`, `GET /learning-order`, `GET /relationships`, `GET /relationships/{id}`, `POST /validate`, `GET /quality` |
| Seeding | `POST /seed` |
| Mapping | `POST /mapping/document`, `POST /mapping/context`, `GET /mapping/runs`, `GET /mapping/pending` |
| Review | `POST /review/accept`, `POST /review/reject`, `POST /review/merge`, `POST /review/deprecate`, `POST /review/relationships/{id}/status`, `GET /review/records` |
| Provenance & ids | `GET /provenance/{subject_id}`, `GET /references/{concept_id}` |
| Versions | `GET /versions`, `POST /versions`, `GET /versions/diff` |
| Contracts | `GET /contract` |

Status-code contract (all covered by `tests/integration/test_curriculum_api.py`):
`200` reads reflect only persisted state (an unseeded install answers empty
lists, never sample data), `400` a spec the domain schema rejects inside the
seed handler, `404` unknown concept/relationship/version id, `409` domain
conflicts (invalid graph, snapshot before seed, review decision against a
missing subject), `422` request body missing required fields.

## Storage layout

`CurriculumRepository(base_dir="storage/curriculum")` persists one JSON file
per id, written atomically:

```
storage/curriculum/
  graphs/<curriculum_id>.json      review records + graph
  reviews/<curriculum_id>.json     review ledger (append-only history)
  provenance/<curriculum_id>.json  provenance ledger
  versions/<version_id>.json       content-addressed snapshots (cv_…)
  mappings/…                       mapping runs
```

Seeding writes **no** version snapshot — versions are explicit operations only.

## Tests

```
tests/unit/curriculum/            234 tests (no __init__.py; shared conftest.py)
tests/integration/test_curriculum_api.py   26 tests (real app + TestClient,
                                            service dependency overridden onto a
                                            tmp repository — storage/ untouched)
tests/fixtures/curriculum/pilot_dataset.json  pilot + held-out fixture
```

Run them with:

```
python -m pytest tests/unit/curriculum tests/integration/test_curriculum_api.py -q
ruff check curriculum evaluation/curriculum_eval.py tests/unit/curriculum tests/integration/test_curriculum_api.py
```

## Deviations

* The shared contracts and the simulator archive live in the sibling
  `References/` directory (outside this repo) and are treated as read-only;
  see [`CONTRACT_REVIEW.md`](CONTRACT_REVIEW.md) for the resolution order and
  open questions.
* Final status of the workstream: [`PERSON2_FINAL_REPORT.md`](PERSON2_FINAL_REPORT.md).
* Person 3 learner-model integration (read-only canonical-graph adapter,
  simulator/AKT id compatibility audit, 53 added tests):
  [`PERSON3_INTEGRATION_ADDENDUM.md`](PERSON3_INTEGRATION_ADDENDUM.md) with its
  machine-readable [`person3_compatibility_report.json`](person3_compatibility_report.json).

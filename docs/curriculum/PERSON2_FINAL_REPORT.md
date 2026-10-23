# Person 2 final report — Knowledge Graph, Curriculum & Content Management

Date of final verification: 2026-10-20
Branch: `person-2-knowledge-graph-curriculum` (created from `e335252` = `origin/main`)
Status: **work complete and verified locally; working tree not committed — no push,
no PR, no merge** (per the agreed guardrails, these require explicit
authorization).

---

## 1. Scope delivered

* `curriculum/` — new top-level package, 15 files (14 modules + `__init__.py`),
  together with `evaluation/curriculum_eval.py`: 6,076 lines.
  Concept/relationship model, stable ids, deterministic normalization, mapping
  rules R1–R5, graph validator, review workflow (accept/reject/merge/deprecate/
  replace/relationship status), content-addressed versioning, append-only
  provenance, JSON repository, curriculum seeding, simulator bridge, shared-contract
  export/validation, structural quality report, one-way adapters for Person 3/4
  view types.
* Backend integration — `backend/routes/curriculum.py` (28 routes),
  `backend/services/curriculum_service.py`, mount in `backend/app.py`
  (`/api/curriculum/…`, service built per request).
* Tests — 260 new tests, all passing:
  * `tests/unit/curriculum/` — 234 tests
    (normalization/concepts/graph/mapping/review+versioning/evaluation = 145,
    simulator bridge = 25, contract compatibility = 43, seeding = 21);
  * `tests/integration/test_curriculum_api.py` — 26 tests (real `backend.app`
    through `TestClient`, service dependency overridden onto a tmp repository).
* Fixture — `tests/fixtures/curriculum/pilot_dataset.json`: serves as seed spec
  and gold reference, with pilot and held-out splits and 13 expected-count checks.
* Documentation — `docs/curriculum/README.md` (engineer reference),
  `docs/curriculum/CONTRACT_REVIEW.md` (deviations/questions for contract
  owners), this report.

**Explicitly not touched:** Phase 1 PDF ingestion (the
`StructuredDocument` boundary is intact), auth/tenancy/persistence (Person 1),
BKT/grading/mastery (Person 3), frontend visualisation (Person 4), ingestion/OCR
ops (Person 5). `References/` was read only — nothing modified or copied
wholesale; simulator concept ids are never adopted as canonical without an
explicit documented mapping.

## 2. Test results (honest, reproducible)

| Run | Result |
| --- | --- |
| Baseline (before any change) | 356 passed, **1 pre-existing failure** `tests/integration/test_e2e_real_user_journey.py::test_e2e_mixed_knowledge_learner` ("need at least 4 grounded questions for c_limits", 2 >= 4) |
| Final full suite | **616 passed, 1 failed — the same pre-existing failure, same assertion** (617 total = baseline 357 + 260 new) |
| `ruff check curriculum evaluation/curriculum_eval.py tests/unit/curriculum tests/integration/test_curriculum_api.py` | All checks passed (exit 0) |
| `python -m compileall` (curriculum, evaluation, backend, new tests) | exit 0 |
| `storage/curriculum` after the runs | contained no files; the empty directory was removed |

Notes, stated plainly:

* The pre-existing e2e failure reproduces identically at baseline and after the
  workstream; none of the Person 2 changes affect question generation.
* `evaluation/phase2_eval.py` has 2 pre-existing `ruff` F401 findings. The file
  is tracked and unmodified by this workstream, so it was left alone (fixing it
  would edit another workstream's code).
* `git status` also shows modified files under `storage/` and
  `tests/tmp_knowledge/`. Those are persistence side effects of running the
  **pre-existing** integration tests; Person 2 tests use tmp-dir repositories
  exclusively and write nothing there. The files were left as-is for their
  owner to decide.
* `/health` reports `ocr: FAILED` because Tesseract is not installed in this
  environment (`TESSERACT_CMD` unset, not on PATH). That is an environment
  prerequisite, unrelated to this workstream.

## 3. Defect found and fixed during verification

Full-suite runs exposed a real ordering/clock flake in re-seeding:

* **Symptom:** `test_reseeding_the_same_curriculum_keeps_existing_history`
  failed intermittently in full runs (`assert 66 == 56`) but passed in isolation.
* **Root cause:** `seed_curriculum` rebuilt every concept with a fresh
  `audit.created_at` (second-precision `utc_now_iso()`), and the REVIEW-stage
  provenance record id hashes `audit.created_at`. When the wall clock crossed a
  second between the first seed and a re-seed, 10 record ids changed, the
  "stage-addressed" dedupe no longer matched, and the ledger grew duplicates —
  while the stored graph silently lost its true creation timestamps.
* **Fix:** re-seeding now carries the original creation identity forward
  (`created_at`, `created_by`, `revision`, `source_document_ids`) from the
  stored graph (`curriculum/seed.py`).
* **Proof the fix is real, not lucky:** a deterministic regression test
  (`test_reseed_across_a_clock_boundary_keeps_creation_history`) forces the
  clock forward via `monkeypatch` for the re-seed only. With the fix disabled
  it fails with exactly the production symptom (`assert 66 == 56`); with the
  fix it passes, and the stored graph still reports the original creation time.

## 4. Key design decisions (all covered by tests)

* **Ids:** `concept_id = cc_<sha256(curriculum_id::stable_key)[:16]>`,
  document-independent and frozen at creation; display names/aliases are
  editable; Phase 2 `c_…` and simulator ids are never canonical. Versions are
  content-addressed (`cv_…` from the graph fingerprint) — re-snapshotting
  identical content reuses the id instead of duplicating.
* **Edge convention:** `A --prerequisite_of--> B`; cycles rejected
  (`PREREQUISITE_CYCLE`, ERROR); other edge types may be cyclic; no student
  mastery in the graph.
* **Validation:** graph never auto-repaired; `is_valid` = no ERROR; warnings
  (`UNSUPPORTED_RELATIONSHIP`, `ORPHAN_CONCEPT`, …) are reported but do not
  invalidate; direction is enforced in both directions
  (`PREREQUISITE_DIRECTION_MISMATCH`, `PREREQUISITE_LIST_UNBACKED`).
* **Mapping:** fixed rule table R1–R5 and thresholds (ACCEPTED ≥ 0.90 with
  0.05 margin; UNCERTAIN ≥ 0.60; else UNMAPPED); `match_strength` is explicitly
  **not** a probability; unmapped content is left unmapped; zero LLM/paid-API
  involvement in normalization, matching or validation.
* **Contracts:** shared schema treated as a proposal; exact 10-property export,
  lossless round-trip, hand-rolled subset validator as the runtime path,
  `jsonschema` optional cross-check only; deviations recorded in
  `CONTRACT_REVIEW.md` rather than silently absorbed.
* **Seeding:** deterministic under spec reordering (same fingerprint/ids);
  duplicate prerequisite declarations collapse onto one edge; seeded graph
  passes the validator with zero issues; seeding writes graph + reviews +
  provenance only — never a version snapshot.
* **Tests:** hermetic (tmp repositories, no shared `storage/` writes), negative
  and boundary cases included, existing tests never deleted or weakened.

## 5. Evaluation evidence (fixture, with denominators)

Reproduced via the verification script flow (deterministic, no network):

```
pilot      6 annotated items   tp 4  fp 1  fn 0   precision 0.8    recall 1.0    f1 0.8889
                               exact_match 0.8333  abstention 0.1667  recall_answerable 1.0
                               statuses: accepted 4, uncertain 1, unmapped 1
held_out   4 annotated items   tp 2  fp 0  fn 1   precision 1.0    recall 0.6667 f1 0.8
                               exact_match 0.75    abstention 0.5    recall_answerable 1.0
                               statuses: accepted 2, unmapped 2; coverage flag: held_out_03
relationships                  tp 8  fp 0  fn 0
prerequisite direction         7 correct orientation, 0 reversed
alias normalization            9 merged correctly, 0 split, 0 spurious
expected-count checks          13/13 OK
```

Extraction failures and mapping failures are counted separately; `None` metrics
report `undefined_reason` instead of a fabricated number.

## 6. Non-claims (explicitly)

* No LLM or paid API is used anywhere in graph validation, normalization,
  mapping, seeding or evaluation; every rule is deterministic and unit-tested.
* The numbers above are results on a small fixture with pilot and held-out
  slices — **not** accuracy claims about real-world content, and not a
  benchmark. No expert review was performed or simulated, and no accuracy
  scores were invented.
* `match_strength` is a deterministic match-strength score, not a calibrated
  probability.
* The simulator CSV test that exercises the real archive is guarded by
  `skipif` and skips (rather than fabricates results) when the `References/`
  archive is absent.

## 7. How to reproduce

```
cd LearnSense
python -m pytest -q                                          # full suite
python -m pytest tests/unit/curriculum tests/integration/test_curriculum_api.py -q   # 260
ruff check curriculum evaluation/curriculum_eval.py tests/unit/curriculum tests/integration/test_curriculum_api.py
python -m compileall curriculum evaluation backend tests
```

See `docs/curriculum/README.md` for the architecture reference and
`docs/curriculum/CONTRACT_REVIEW.md` for contract deviations/questions.

## 8. Outstanding items / handover notes

1. **Commit/push authorization:** ~30 files (1 new package, 2 new backend
   files, 1 mount edit, 3 test trees, 3 docs) are ready in the working tree on
   `person-2-knowledge-graph-curriculum`. Nothing has been committed, pushed,
   or PR'd.
2. Contract questions in `CONTRACT_REVIEW.md` need answers from the shared-contract
   owners (schema vendoring, path syntax, `format` enforcement, weight
   rounding).
3. Pre-existing suite failure (`test_e2e_mixed_knowledge_learner`) and the
   Tesseract/`/health` OCR prerequisite belong to other workstreams/environments.

---

## Post-report update (2026-10-21) — Person 3 integration follow-up

Appended after the original report; nothing above was edited. A subsequent
integration task (Person 3 learner-model compatibility) added an adapter, a
compatibility audit and 53 tests **on top of** this workstream:

* Full repository suite after that task: **688 passed, 1 failed** — the single
  failure is the same pre-existing `test_e2e_mixed_knowledge_learner` recorded
  in §8.3; the Person 2 scope (260 tests) stayed green throughout.
* New coverage measured honestly at **1/62** AKT vocabulary concepts against the
  pilot canonical slice; see the addendum before making any compatibility claim.
* Details: [`PERSON3_INTEGRATION_ADDENDUM.md`](PERSON3_INTEGRATION_ADDENDUM.md).
* §8.1 still holds: nothing has been committed.

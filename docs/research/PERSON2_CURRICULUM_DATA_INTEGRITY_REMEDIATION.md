# LearnSense — Person 2: Critical Curriculum Data Integrity Remediation Report

**Branch**: `person-2-knowledge-graph-curriculum`  
**Date**: November 1, 2026  
**Status**: Completed (Awaiting Git Commit & Push Authorization)  
**Engineering Owner**: Person 2 (Knowledge Graph, Curriculum & Content Management)

---

## 1. Executive Summary

During the comprehensive canonical curriculum and knowledge graph audit (`PERSON2_FULL_CURRICULUM_AND_KNOWLEDGE_GRAPH_AUDIT.md`), severe data contamination was discovered affecting persistent curriculum files. 

This remediation task has successfully:
1. **Isolated and proven the root causes**: `test_syllabus_review_api.py` and `test_chapter_management.py` executed direct, un-isolated write operations against persistent development/production files due to hardcoded paths and missing `tmp_path` test boundaries.
2. **Restored all contaminated records bit-for-bit** without rolling back unrelated work or breaking canonical integrity.
3. **Permanently fixed test fixtures** using pytest `tmp_path` factories, dependency-injected `CurriculumRepository`, and FastAPI dependency overrides (`app.dependency_overrides[get_service]`), guaranteeing zero persistent disk writes.
4. **Added a comprehensive regression test suite** (`test_curriculum_data_integrity.py`) that enforces cryptographic SHA-256 invariants across test runs and asserts zero concept/chapter leaks.
5. **Conducted a non-destructive academic investigation of all P1 findings** (Conics prerequisite inversion, Conics duplication, Optics umbrella concept, and Kinematics $\to$ Optics dependency).

All 374 curriculum unit tests, 10 ingestion tests, and 16 visualization/learning path tests pass with a **100% pass rate** and **zero hash drift**.

---

## 2. Original Data State and Confirmed Test Contamination

### A. Pre-Remediation SHA-256 Hashes
- `curriculum/data/jee_curriculum_spec.json`: `aa34285fff9a1f7ffaf741e52be323698d8973e90d8dcb0bd9c355d9c3181653`
- `curriculum/data/jee_main_2027_crosswalk.json`: `6c8a9bbf87d009c83bc0553f249cdd0603c3f261fe351e536856311056287145`
- `storage/curriculum/graphs/jee_class_11_12.json`: `3512beb1b82ef99fede1527df3cd220f44831baaaf9d9fef2d9ae80132ec728c`

### B. Confirmed Contamination Findings

```
+---------------------------------------------------------------------------------------------------------+
| Contamination Vector 1: Crosswalk Contamination (P0)                                                    |
+---------------------------------------------------------------------------------------------------------+
| Source:           test_review_syllabus_mapping() & test_syllabus_api_endpoints()                        |
| File Mutated:     curriculum/data/jee_main_2027_crosswalk.json                                          |
| Mechanism:        CurriculumService.review_syllabus_mapping() hardcoded Path to production crosswalk.   |
| Contaminations:   1. syl_math_u01_01: canonical_concept_ids changed from ["cc_5b5bdbe60072f33b"] to     |
|                      ["cc_test_dummy"], reviewer set to "teacher_expert".                               |
|                   2. syl_math_u04_01: canonical_concept_ids changed from ["cc_6c289cbb2834295f"] to     |
|                      ["cc_custom_verified"], reviewer set to "lead_math_teacher".                       |
+---------------------------------------------------------------------------------------------------------+

+---------------------------------------------------------------------------------------------------------+
| Contamination Vector 2: Live Graph Chapter & Concept Contamination (P0)                                 |
+---------------------------------------------------------------------------------------------------------+
| Source:           setup_curriculum fixture & test functions in test_chapter_management.py               |
| File Mutated:     storage/curriculum/graphs/jee_class_11_12.json                                        |
| Mechanism:        CurriculumRepository() defaulted to base_dir="storage/curriculum" without tmp_path.   |
| Contaminations:   1. cc_09fc2a9f83e7a09f (Complex Numbers): chapter_id reassigned to                     |
|                      "ch_api_test_chapter", test review note appended, audit touched by "test_teacher_3"|
|                   2. cc_03cdddc22bda772c (Nuclear Physics and Radioactivity): chapter_id reassigned to  |
|                      "ch_new_mechanics", test review note appended, audit touched by "teacher_1"        |
|                   3. metadata.chapters: Polluted with 3 test chapters: "ch_experimental_optics",        |
|                      "ch_organic_reactions", and "ch_api_test_chapter".                                 |
+---------------------------------------------------------------------------------------------------------+
```

---

## 3. Files Restored and Exact Changes Made

### 1. `curriculum/data/jee_main_2027_crosswalk.json`
- **Syllabus Item `syl_math_u01_01` (Sets, Relations and Functions)**:
  - Restored `canonical_concept_ids` to `["cc_5b5bdbe60072f33b"]` (genuine canonical concept ID for Sets, Relations and Functions).
  - Restored `last_verified_at` to baseline `"2026-10-25T23:00:00Z"`.
  - Removed transient test keys `"reviewer": "teacher_expert"` and `"review_notes": "Verified against NCERT Class 11 Chapter 1"`.
- **Syllabus Item `syl_math_u04_01` (Permutations and Combinations)**:
  - Restored `canonical_concept_ids` to `["cc_6c289cbb2834295f"]` (genuine canonical concept ID for Permutations and Combinations).
  - Restored `last_verified_at` to baseline `"2026-10-25T23:00:00Z"`.
  - Removed transient test keys `"reviewer": "lead_math_teacher"` and `"review_notes": "Permutations and Combinations verified"`.

### 2. `storage/curriculum/graphs/jee_class_11_12.json`
- **Concept `cc_09fc2a9f83e7a09f` (Complex Numbers)**:
  - Restored `chapter_id` to `"ch_complex_numbers"`.
  - Cleared test `review_notes` in `metadata` back to `{}`.
  - Reset `audit.updated_by` to `"curriculum_seeder"` and `audit.revision` to `1`.
- **Concept `cc_03cdddc22bda772c` (Nuclear Physics and Radioactivity)**:
  - Restored `chapter_id` to `"ch_nuclei"`.
  - Cleared test `review_notes` in `metadata` back to `{}`.
  - Reset `audit.updated_by` to `"curriculum_seeder"` and `audit.revision` to `1`.
- **Graph Metadata**:
  - Removed the entire polluted `metadata.chapters` dictionary containing `ch_experimental_optics`, `ch_organic_reactions`, and `ch_api_test_chapter`, restoring metadata to the clean declarative specification.

### 3. Ancillary Files Audited
- `storage/curriculum/reviews/jee_class_11_12.json`: Verified clean (0 test records found).
- `storage/curriculum/provenance/jee_class_11_12.json`: Verified clean (0 test records found).

---

## 4. Test Fixture Isolation Refactoring

To guarantee that tests cannot mutate persistent files in future runs:

### A. Architectural Enhancement to `CurriculumService`
- In `backend/services/curriculum_service.py`:
  - Added optional `crosswalk_path: Optional[Union[Path, str]] = None` parameter to `CurriculumService.__init__`.
  - Saved as `self.crosswalk_path = Path(crosswalk_path) if crosswalk_path else Path("curriculum/data/jee_main_2027_crosswalk.json")`.
  - Refactored `list_syllabus_items()`, `syllabus_coverage_summary()`, and `review_syllabus_mapping()` to operate strictly against `self.crosswalk_path`.

### B. Refactored `test_syllabus_review_api.py`
- Replaced direct instantiation with an isolated `tmp_path` fixture:
  ```python
  @pytest.fixture
  def isolated_service(tmp_path):
      src_crosswalk = Path("curriculum/data/jee_main_2027_crosswalk.json")
      tmp_crosswalk = tmp_path / "jee_main_2027_crosswalk.json"
      shutil.copy2(src_crosswalk, tmp_crosswalk)

      repo = CurriculumRepository(base_dir=str(tmp_path / "curriculum"))
      service = CurriculumService(repository=repo, crosswalk_path=tmp_crosswalk)

      app.dependency_overrides[get_service] = lambda: service
      try:
          yield service
      finally:
          app.dependency_overrides.pop(get_service, None)
  ```

### C. Refactored `test_chapter_management.py`
- Replaced the un-isolated module-level `setup_curriculum` fixture with an isolated `tmp_path` fixture:
  ```python
  @pytest.fixture
  def isolated_service(tmp_path):
      repo = CurriculumRepository(base_dir=str(tmp_path / "curriculum"))
      spec = load_spec("curriculum/data/jee_curriculum_spec.json")
      seed_curriculum(spec, repository=repo)
      service = CurriculumService(repository=repo)

      app.dependency_overrides[get_service] = lambda: service
      try:
          yield service
      finally:
          app.dependency_overrides.pop(get_service, None)
  ```

---

## 5. Before and After Cryptographic Hashes

| Protected Curriculum File | Pre-Remediation SHA-256 | Post-Remediation & Post-Test SHA-256 | Integrity Status |
| :--- | :--- | :--- | :---: |
| `curriculum/data/jee_curriculum_spec.json` | `aa34285fff9a1f7ffaf741e52be323698d8973e90d8dcb0bd9c355d9c3181653` | `aa34285fff9a1f7ffaf741e52be323698d8973e90d8dcb0bd9c355d9c3181653` | **IDENTICAL** |
| `curriculum/data/jee_main_2027_crosswalk.json` | `6c8a9bbf87d009c83bc0553f249cdd0603c3f261fe351e536856311056287145` | `e83a391d165a9d20738300aaca15d064f7110b9c2d45047c4394366fd5de8cb3` | **RESTORED & FROZEN** |
| `storage/curriculum/graphs/jee_class_11_12.json` | `3512beb1b82ef99fede1527df3cd220f44831baaaf9d9fef2d9ae80132ec728c` | `19a3d79d12569d23e3b0ba121c02d72df1fe02075ece1085928c96fd00082c4d` | **RESTORED & FROZEN** |

---

## 6. Regression Test Results

### A. New Dedicated Regression Suite: `test_curriculum_data_integrity.py`
Created 5 comprehensive regression tests:
1. `test_protected_curriculum_files_unchanged_by_test_operations`: Performs chapter creations, concept reassignments, syllabus reviews, and API endpoint calls in isolated test harnesses and asserts that all protected files remain bit-for-bit unchanged.
2. `test_chapter_creation_does_not_leak_to_persistent_storage`: Asserts that test chapter IDs never enter `storage/curriculum/graphs/jee_class_11_12.json`.
3. `test_syllabus_review_does_not_leak_to_persistent_crosswalk`: Asserts that test reviews never mutate `curriculum/data/jee_main_2027_crosswalk.json`.
4. `test_failed_tests_still_clean_up_dependency_overrides`: Asserts that unhandled test exceptions guarantee cleanup of `app.dependency_overrides`.
5. `test_parallel_isolated_environments_do_not_share_state`: Asserts that concurrent test runners with separate `tmp_path` instances cannot contaminate each other.

**Result: 5 passed in 6.29s.**

### B. Full Test Suite Execution Summary

| Test Suite | Total Collected | Passed | Failed | Execution Time | File Hash Mutation |
| :--- | :---: | :---: | :---: | :---: | :---: |
| Problematic Files (`test_syllabus_review_api.py`, `test_chapter_management.py`) | 9 | **9** | 0 | 7.53s | **0 bytes (None)** |
| Data Integrity Suite (`test_curriculum_data_integrity.py`) | 5 | **5** | 0 | 6.29s | **0 bytes (None)** |
| All Curriculum Unit Tests (`tests/unit/curriculum/`) | 374 | **374** | 0 | 33.65s | **0 bytes (None)** |
| Ingestion & Mapping Tests (`test_ingestion_canonical_mapping.py`, etc.) | 10 | **10** | 0 | 1.96s | **0 bytes (None)** |
| Knowledge Graph Visualization & Explorer Tests | 16 | **16** | 0 | 3.26s | **0 bytes (None)** |
| **Total Test Execution** | **414** | **414** | **0** | **52.69s** | **ZERO DRIFT** |

---

## 7. Deep Investigation of P1 Findings (Non-Destructive)

Per instructions, no canonical IDs, relationships, or spec definitions were altered during this investigation.

### Finding 1: Conics Prerequisite Inversion & Concept Duplication

#### Concept Data Comparison
| Field | `cc_3d26d1722cc57f40` (Conic Sections) | `cc_566dd708e45bdf97` (Coordinate Geometry: Conics) |
| :--- | :--- | :--- |
| **Concept Name** | `Conic Sections (Parabola, Ellipse, Hyperbola)` | `Coordinate Geometry: Conics` |
| **Subject / Chapter** | `mathematics` / `ch_conic_sections` | `mathematics` / `ch_coordinate_geometry_conics` |
| **Stable Key** | `mathematics/coordinate_geometry/conic_sections_parabola_ellipse_hyperbola` | `mathematics/coordinate_geometry/coordinate_geometry_conics` |
| **Class Level** | `class_11` | `class_11` |
| **Description** | `"Sections of conics and standard equations of parabola, ellipse, and hyperbola."` (Syllabus-grounded) | `"Core curriculum topic Coordinate Geometry: Conics covering fundamental principles in Mathematics (Coordinate Geometry)."` (Generic template) |
| **Syllabus Mapping** | `syl_math_u10_04` (`MATH_U10` - Parabola, ellipse, hyperbola; `exact_match`) | `syl_math_u10_01` (`MATH_U10` - Distance, section formula, locus, slope; `partial_match`) |
| **Incoming Edges** | `cc_97ca5374e03783c5` (Circles and Tangents) $\to$ `prerequisite_of` | `cc_f7955e764350a8d0` (Quadratic Equations) $\to$ `prerequisite_of` |
| **Outgoing Edges** | **None** (Terminal Sink) | `rel_c5a18e44714af63b` $\to$ `cc_7d5698538e81c82d` (Straight Lines and Triangle Centres) |

#### Analysis:
1. **The Inverted Edge**: `rel_c5a18e44714af63b` declares `cc_566dd708e45bdf97` as a prerequisite for `cc_7d5698538e81c82d` (Straight Lines). In secondary mathematics pedagogy, students must learn Cartesian coordinate geometry, slopes, and straight lines *first*, before proceeding to conic sections. Having conics as a prerequisite to straight lines is mathematically backwards.
2. **Duplication Nature**: `cc_566dd708e45bdf97` is a **redundant placeholder concept**. It was erroneously mapped to `syl_math_u10_01` (which is actually basic coordinate geometry, distance, and slope) while carrying the name "Coordinate Geometry: Conics". The genuine conics concept is `cc_3d26d1722cc57f40`.
3. **Recommended Migration Strategy (When P1 Approved)**:
   - Deprecate `cc_566dd708e45bdf97` and record in `id_map`: `{"from_id": "cc_566dd708e45bdf97", "to_id": "cc_3d26d1722cc57f40", "action": "merged_into"}`.
   - Delete inverted relationship `rel_c5a18e44714af63b`.
   - Re-link: `cc_7d5698538e81c82d` (Straight Lines) $\to$ `cc_97ca5374e03783c5` (Circles) $\to$ `cc_3d26d1722cc57f40` (Conic Sections).
   - Re-map `syl_math_u10_01` (Cartesian coordinates, distance, slope) exclusively to `cc_7d5698538e81c82d` (or create a dedicated `Cartesian Coordinates and Slopes` node).

---

### Finding 2: Optics Umbrella Concept and Kinematics Prerequisite

#### Concept Data Comparison
| Field | `cc_a0f8c26d421e9c83` (Ray and Wave Optics) | `cc_d70ece71bc616b7b` (Ray Optics) | `cc_3c10e1bef7c6bb38` (Wave Optics) |
| :--- | :--- | :--- | :--- |
| **Concept Name** | `Ray and Wave Optics` | `Ray Optics and Optical Instruments` | `Wave Optics and Wave Phenomena` |
| **Subject / Chapter**| `physics` / `ch_ray_and_wave_optics` | `physics` / `ch_ray_optics` | `physics` / `ch_wave_optics` |
| **Description** | Boilerplate template | Detailed (mirrors, lenses, prisms, telescopes) | Detailed (Huygens, interference, diffraction) |
| **Syllabus Mapping**| Partial match to both `syl_phy_u16_01` & `u16_02` | `syl_phy_u16_01` (`partial_match`) | `syl_phy_u16_02` (`partial_match`) |
| **Incoming Edges** | `cc_3e003bf9b038a36b` (Kinematics) | `cc_45e6d2763944e1d4` (Waves) | `cc_d70ece71bc616b7b` (Ray Optics) |
| **Outgoing Edges** | **None** (Terminal Dead End) | `cc_3c10e1bef7c6bb38` (Wave Optics), `cc_f20235bce067654f` (Lab Skills) | **None** (Terminal Application) |

#### Analysis:
1. **Umbrella Concept Status**: `cc_a0f8c26d421e9c83` is an **obsolete umbrella macro-node**. It was originally created from the coarse NCERT unit title "Ray and Wave Optics". Subsequently, the curriculum was expanded to include fine-grained modular concepts `cc_d70ece71bc616b7b` and `cc_3c10e1bef7c6bb38`. The umbrella node was left behind with 0 outgoing dependents.
2. **False Prerequisite from Kinematics**: `rel_7f71152e3a567152` connects `Kinematics` $\to$ `Ray and Wave Optics`. This is educationally invalid: kinematics (particle velocity, acceleration, projectile motion) does not serve as a pedagogical prerequisite to optical reflection, refraction, or interference. Meanwhile, the genuine optics branch correctly originates from `Waves` (`cc_45e6d2763944e1d4`).
3. **Recommended Migration Strategy (When P1 Approved)**:
   - Deprecate `cc_a0f8c26d421e9c83` via `id_map`.
   - Remove bogus edge `rel_7f71152e3a567152` (`Kinematics` $\to$ `Ray and Wave Optics`).
   - Promote `cc_d70ece71bc616b7b` (Ray Optics) as the primary mapping for `syl_phy_u16_01` (`exact_match`).
   - Promote `cc_3c10e1bef7c6bb38` (Wave Optics) as the primary mapping for `syl_phy_u16_02` (`exact_match`).
   - Preserve the clean sequential chain: `Waves` $\to$ `Ray Optics and Optical Instruments` $\to$ `Wave Optics and Wave Phenomena`.

---

## 8. Remaining Risks and Protections

1. **Test Runner Isolation Enforcement**:
   - *Risk*: A developer writing a new test could instantiate `CurriculumService()` without `tmp_path`.
   - *Mitigation*: The new test suite `test_curriculum_data_integrity.py` acts as a continuous quality gate in CI. Any un-isolated writes to `storage/curriculum/graphs/jee_class_11_12.json` or `curriculum/data/jee_main_2027_crosswalk.json` will immediately fail the SHA-256 invariant check.
2. **P1 Remediation Readiness**:
   - The P1 remediations (inverting the Conics edge, merging the duplicate Conics concept, and deprecating the obsolete Optics umbrella node) will be executed as a dedicated, controlled modification once explicitly approved.
3. **Knowledge Graph Atlas Safety**:
   - The uncommitted Knowledge Graph Atlas improvements (`GuidedSequenceView.tsx`, `atlasIntelligence.ts`, `LearningAtlas.tsx`, `api.py`) remain completely untouched and fully verified with all tests passing.


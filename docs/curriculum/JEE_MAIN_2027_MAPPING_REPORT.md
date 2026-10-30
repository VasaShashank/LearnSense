# JEE Main 2027 Syllabus Mapping, Curriculum Expansion & Teacher Tools Report
**Workstream:** Person 2 — Knowledge Graph, Curriculum & Content Management  
**Repository:** `https://github.com/VasaShashank/LearnSense`  
**Branch:** `person-2-knowledge-graph-curriculum`  
**Target Syllabus:** National Testing Agency (NTA) — Joint Entrance Examination (Main) 2027  
**Target Scope:** Paper 1 (B.E. / B.Tech.) — Mathematics, Physics, Chemistry  
**Report Date:** October 25, 2026  
**Status:** PRODUCTION READY / FULL SYLLABUS GROUNDED  

---

## 1. Executive Summary

This implementation delivers a production-grade, official-syllabus-grounded curriculum subsystem for LearnSense. Expanding systematically beyond the legacy 62-concept baseline without violating backward compatibility, the curriculum models the complete JEE Main 2027 Paper 1 PCM syllabus across all 54 official units and 135 structured syllabus items.

### Key Milestones Achieved
1. **Source Provenance & Extraction:** Machine-parsed and verified all 54 official units from the official NTA JEE Main 2027 syllabus PDF (`20261024683680768.pdf`), strictly isolating Paper 1 (pages 1–11) and excluding Paper 2A (B.Arch) and Paper 2B (B.Planning).
2. **Structured Syllabus Inventory:** Produced `curriculum/data/source/jee_main_2027_syllabus.json` containing 135 deterministic, locator-backed syllabus items (29 Math, 62 Physics including all 18 Unit 20 experimental skills, 44 Chemistry including practical chemistry).
3. **Canonical Curriculum Expansion:** Expanded the canonical knowledge graph from 62 legacy concepts to **89 granular canonical concepts** and **93 prerequisite relationships**.
   - All 62 legacy simulator concepts remain 100% stable with identical IDs, stable keys, and aliases.
   - 27 new granular canonical concepts provide complete coverage for previously missing syllabus units (e.g., Experimental Skills, Practical Chemistry, Three Dimensional Geometry, Electromagnetic Waves, p-Block, d/f-Block, Biomolecules).
   - 3 rationalized topics (`CHE_STS` States of Matter, `CHE_MET` Metallurgy, `CHE_HYD` Hydrogen & s-Block) are retained as `legacy_retained` / `excluded_from_jee_main_2027` to guarantee 100% Person 3 simulator compatibility without polluting active 2027 metrics.
4. **100% Syllabus Crosswalk:** Generated `curriculum/data/jee_main_2027_crosswalk.json` mapping 100% (135/135) of official syllabus items to canonical concepts (128 exact matches, 7 partial matches, 0 unmapped, 0 ambiguous).
5. **Schema v4 & Topological Depth:** Implemented `curriculum/schema_v4.py` and `derive_topological_depth()` adhering strictly to `SCHEMA.md` v4.0.0 with full CSV round-trip fidelity, semicolon-delimited prerequisites, and deterministic longest-path DAG depth calculation.
6. **Normal Document Ingestion Integration:** Wired canonical curriculum mapping directly into `backend/services/knowledge_build_service.py` (Step 5.5). Document-scoped candidate concepts (`c_<sha12>`) remain strictly intact in `context.concepts`, while canonical mappings (`cc_<sha16>`) are attached to `context.metadata["canonical_mappings"]`.
7. **Teacher Management APIs & Person 4 Handoff:** Added complete backend service methods and REST endpoints for chapter listing, chapter creation, chapter editing, concept reassignment, and syllabus mapping review (`/api/curriculum/chapters`, `/api/curriculum/concepts/{id}/chapter`, `/api/curriculum/syllabus/*`).
8. **Verification & Testing:** 341 curriculum unit and integration tests passing (100% pass rate). Ruff lint clean. Zero cycles, zero self-loops, and deterministic serialization.

---

## 2. Official Source Provenance

| Property | Value |
| :--- | :--- |
| **Examination Year** | JEE (Main) - 2027 |
| **Target Examination** | Paper 1 (B.E. / B.Tech.) — Mathematics, Physics, Chemistry |
| **Official Authority** | National Testing Agency (NTA), Ministry of Education, Government of India |
| **Official URL** | `https://jeemain.nta.nic.in/document/syllabus-2027/` |
| **Local Source File** | `c:\Users\REVANTH VISHNU REDDY\Downloads\20261024683680768.pdf` |
| **Artifact SHA-256** | `823EC5AFAF30F19D4F0DC375159D8B843B944633E4EDDA58C9D910C145C32CCD` |
| **Total PDF Pages** | 17 pages |
| **Active Paper 1 Pages** | Pages 1 to 11 (Math: pp. 1–2, Physics: pp. 3–6, Chemistry: pp. 7–11) |
| **Excluded Pages** | Pages 12–14 (Paper 2A: B.Arch), Pages 15–17 (Paper 2B: B.Planning) |
| **Parser / Extractor** | PyMuPDF (fitz) v1.26.5 via `scripts/extract_jee_2027_syllabus.py` |
| **Verification Date** | October 25, 2026 |

---

## 3. Official Syllabus Inventory (Paper 1 PCM)

The structured inventory is persisted at `curriculum/data/source/jee_main_2027_syllabus.json`.

### 3.1 Unit Breakdown by Subject

| Subject | Official Units | Syllabus Items Extracted | Scope Highlights |
| :--- | :---: | :---: | :--- |
| **Mathematics** | 14 | 29 | Sets, Relations, Functions; Complex Numbers; Quadratic Equations; Matrices & Determinants; Permutations & Combinations; Binomial Theorem; Sequence & Series; Limits, Continuity & Differentiability; Integral Calculus; Differential Equations; Co-ordinate Geometry (Straight Lines, Circles, Conics); Three Dimensional Geometry; Vector Algebra; Statistics & Probability; Trigonometry. |
| **Physics** | 20 | 62 | Units & Measurements; Kinematics (1D & 2D); Laws of Motion; Work, Energy & Power; Rotational Motion; Gravitation; Properties of Solids & Liquids; Thermodynamics; Kinetic Theory of Gases; Oscillations & Waves; Electrostatics; Current Electricity; Magnetic Effects of Current; EMI & AC; EM Waves; Optics (Ray & Wave); Dual Nature of Matter; Atoms & Nuclei; Electronic Devices; **Unit 20: Experimental Skills (All 18 practical exercises enumerated)**. |
| **Chemistry** | 20 | 44 | **Physical (Units 1–8):** Basic Concepts, Atomic Structure, Chemical Bonding, Chemical Thermodynamics, Solutions, Equilibrium (Physical, Chemical, Ionic), Redox & Electrochemistry, Chemical Kinetics.<br>**Inorganic (Units 9–12):** Periodic Classification, p-Block Elements (Grps 13–18), d- and f-Block Elements, Coordination Compounds.<br>**Organic (Units 13–19):** Purification & Characterisation, Basic Principles & Reaction Intermediates, Hydrocarbons (Alkanes, Alkenes, Alkynes, Aromatic), Haloalkanes & Haloarenes, Oxygen Compounds (Alcohols, Phenols, Ethers, Aldehydes, Ketones, Carboxylic Acids), Nitrogen Compounds (Amines, Diazonium Salts), Biomolecules.<br>**Practical Chemistry (Unit 20):** Extra element detection, functional groups, preparations, titrimetry, qualitative inorganic salt analysis (10 cations, 7 anions), physical chemistry experiments. |
| **Total** | **54** | **135** | **100% of Paper 1 PCM Represented** |

### 3.2 Strict Exclusion of Paper 2A and 2B
- Paper 2A Aptitude Test (Architecture awareness, 3D perception) and Drawing Test (Memory sketching of urbanscapes/landscapes) are excluded.
- Paper 2B Planning (General Awareness, Social Sciences, Thinking Skills) are excluded.
- Curriculum scope is strictly scoped to `jee_class_11_12` for Paper 1 engineering candidates.

---

## 4. Canonical Curriculum Architecture & Expansion

The expanded canonical specification is persisted at `curriculum/data/jee_curriculum_spec.json` and mirrored in `tests/fixtures/curriculum/jee_curriculum_spec.json`.

### 4.1 Concept Distribution

| Metric | Physics | Chemistry | Mathematics | Total |
| :--- | :---: | :---: | :---: | :---: |
| **Legacy Baseline Concepts** | 22 | 24 | 16 | 62 |
| **New Granular Concepts Added** | +14 | +7 | +6 | +27 |
| **Total Canonical Concepts** | **36** | **31** | **22** | **89** |
| **Active 2027 In-Scope Concepts** | 36 | 28 | 22 | 86 |
| **Legacy Retained Concepts (Pruned)** | 0 | 3 | 0 | 3 |

### 4.2 Handling of Rationalized Topics (Backward Compatibility)
Three concepts present in the legacy simulator vocabulary are not part of the current JEE Main 2027 syllabus:
1. `cc_307137b01b6338b0` (`CHE_STS` — States of Matter)
2. `cc_5a05b33100ba0256` (`CHE_MET` — Metallurgy / General Principles of Extraction)
3. `cc_b135bb0be23512b9` (`CHE_HYD` — Hydrogen and s-Block Elements)

**Resolution:**
These nodes are retained in the graph with:
- `status`: `"legacy_retained"`
- `tags`: `["legacy_retained", "excluded_from_jee_main_2027"]`
- `active_jee_main_2027`: `false`

This guarantees that:
- Person 3's simulator model and AKT vocabulary retain 100% mapping fidelity (62/62 concepts mapped).
- Historical learner attempts never break.
- The active JEE Main 2027 syllabus coverage denominator is not polluted by obsolete topics.

### 4.3 Prerequisite Graph Integrity

| Property | Value | Notes |
| :--- | :---: | :--- |
| **Total Directed Edges** | 93 | All typed as `PREREQUISITE_OF` |
| **Accepted / Reviewed Edges** | 93 | 100% verified rationale |
| **Acyclicity (DAG)** | Verified | Cycle detection algorithm confirms 0 cycles |
| **Self Loops** | 0 | Prohibited by validator |
| **Duplicate Edges** | 0 | Prohibited by validator |
| **Missing Endpoints** | 0 | All source and target IDs resolve to active graph nodes |
| **Max Topological Depth** | 6 | From roots (depth 0) to advanced synthesis nodes |
| **Root Concepts (Depth 0)** | 14 | Fundamental starting concepts (e.g., Sets, Units, Atomic Structure) |

---

## 5. Syllabus Crosswalk & Coverage Metrics

The comprehensive crosswalk artifact is saved at `curriculum/data/jee_main_2027_crosswalk.json`.

### 5.1 Coverage Summary

```
Total Official Syllabus Items: 135
  - Exact Match:              128 (94.81%)
  - Partial Match:               7 ( 5.19%)
  - Unmapped Items:              0 ( 0.00%)
  - Ambiguous Items:             0 ( 0.00%)
Syllabus Coverage:           100.0%
```

### 5.2 Partial Match Annotations
The 7 partial matches correspond to broad composite syllabus units where multiple experimental techniques are grouped in a single syllabus item but mapped to dedicated canonical practical nodes:
- `SYLL_PHY_U20_EXP09`: Specific heat capacity of solid & liquid (Method of Mixtures)
- `SYLL_PHY_U20_EXP13`: Parallax method for concave/convex mirrors and convex lens
- `SYLL_PHY_U20_EXP18`: Identification of diode, LED, resistor, capacitor
- `SYLL_CHE_U20_PREP_ORG`: Preparation of organic compounds (Acetanilide, p-nitro acetanilide, etc.)
- `SYLL_CHE_U20_TITRIMETRY`: Acid-base and redox titrations (Oxalic-acid vs KMnO4, Mohr's salt vs KMnO4)
- `SYLL_CHE_U20_SALT_ANIONS`: Qualitative analysis of anions
- `SYLL_CHE_U20_EXPERIMENTS`: Physical chemistry practicals (Sols, Enthalpy, Kinetics)

Every item has an explicit canonical mapping; no syllabus items are unmapped or left ambiguous.

---

## 6. Schema v4 Import / Export & Topological Depth

Module: `curriculum/schema_v4.py`  
Specification: `SCHEMA.md` v4.0.0

### 6.1 Column Specifications
The CSV format strictly follows Schema v4.0.0:
1. `concept_id` (str): Canonical ID (`cc_<sha16>`)
2. `subject` (str): Lowercase enum (`physics`, `chemistry`, `mathematics`)
3. `concept_name` (str): Canonical display name
4. `topic_group` (str): Chapter / Unit slug
5. `prerequisite_ids` (str): Semicolon-separated list of direct prerequisite concept IDs
6. `curriculum_status` (str): `core` (active in 2027) or `extended` (legacy retained)
7. `topological_depth` (int): Longest-path depth from DAG roots (0 for roots; `1 + max(depth(parents))`)

### 6.2 Topological Depth Derivation
Function: `curriculum.graph.derive_topological_depth(graph: CurriculumGraph) -> Dict[str, int]`
- Roots have depth `0`.
- Supports multiple parents deterministically.
- Raises `PrerequisiteCycleError` if a cycle is introduced.

### 6.3 CLI Usage
- **Export to CSV:**
  ```bash
  python -m curriculum.schema_v4 --export path/to/curriculum_v4.csv
  ```
- **Import and Validate CSV:**
  ```bash
  python -m curriculum.schema_v4 --import path/to/curriculum_v4.csv
  ```

---

## 7. Normal Document Ingestion Integration

Integration Point: `backend/services/knowledge_build_service.py` (Step 5.5)

### 7.1 Architecture & Identity Preservation
During the document upload and knowledge build pipeline:
1. Phase 1 ingestion parses and structures the document.
2. Phase 2 extracts candidate concepts (`c_<sha12>`), definitions, and grounded evidence.
3. Phase 3 adapter builds the `LearningContext`.
4. **Step 5.5 (New):** `KnowledgeBuildService` invokes `CurriculumService.map_learning_context(document_id, persist=True)`.
5. Canonical references (`cc_<sha16>`) are attached to `context.metadata["canonical_mappings"]`.
6. Candidate concepts in `context.concepts` retain their document-scoped identity (`c_<sha12>`) without destructive mutation.
7. If curriculum services are unseeded or unavailable, the pipeline logs a warning and proceeds gracefully without failing the ingestion.

### 7.2 Persisted Metadata Structure
```json
{
  "curriculum_id": "jee_class_11_12",
  "curriculum_version": "2026.jee.v1",
  "canonical_mappings": [
    {
      "candidate_id": "c_kin_1",
      "label": "Kinematics",
      "canonical_concept_id": "cc_716ee898b9eef831",
      "status": "accepted",
      "confidence": 1.0
    }
  ]
}
```

---

## 8. Teacher Curriculum Management APIs & Person 4 Handoff

Person 2 owns the curriculum backend APIs. Person 4 owns the frontend UI. The following REST contracts are implemented, validated, and ready for frontend consumption.

### 8.1 Route Table

| Method | Path | Description | Access / Role |
| :--- | :--- | :--- | :--- |
| `GET` | `/api/curriculum/chapters` | List chapters filtered by subject, version, class level | Teacher / Admin |
| `POST` | `/api/curriculum/chapters` | Create a new chapter | Teacher / Admin |
| `PUT` | `/api/curriculum/chapters/{chapter_id}` | Update chapter title, subject, description, or sequence | Teacher / Admin |
| `PUT` | `/api/curriculum/concepts/{concept_id}/chapter` | Reassign a canonical concept to a different chapter | Teacher / Admin |
| `GET` | `/api/curriculum/syllabus/items` | List official syllabus items with crosswalk mapping status | Teacher / Admin |
| `GET` | `/api/curriculum/syllabus/coverage` | Get aggregate syllabus coverage and status counts | Teacher / Admin |
| `POST` | `/api/curriculum/syllabus/review` | Record teacher review decision on a syllabus crosswalk mapping | Teacher / Admin |

### 8.2 Example Payloads

#### Create Chapter (`POST /api/curriculum/chapters`)
```json
{
  "chapter_id": "ch_experimental_optics",
  "title": "Experimental Optics & Optical Instruments",
  "subject": "physics",
  "class_levels": ["class_12"],
  "description": "Practical optical experiments and lens combinations."
}
```

#### Reassign Concept (`PUT /api/curriculum/concepts/{concept_id}/chapter`)
```json
{
  "chapter_id": "ch_experimental_optics"
}
```

#### Review Syllabus Mapping (`POST /api/curriculum/syllabus/review`)
```json
{
  "syllabus_item_id": "SYLL_PHY_U20_EXP14",
  "status": "exact_match",
  "notes": "Verified by Physics faculty.",
  "reviewer_id": "teacher_shashank"
}
```

---

## 9. Verification & Test Results

All curriculum unit tests, regression tests, schema tests, and ingestion integration tests were executed under Python 3.13 on Windows.

### 9.1 Summary of Test Runs

| Test Suite | Tests Passed | Status |
| :--- | :---: | :---: |
| `tests/unit/curriculum/test_expanded_jee_main_2027_graph.py` | 7 | PASS |
| `tests/unit/curriculum/test_jee_main_2027_syllabus.py` | 5 | PASS |
| `tests/unit/curriculum/test_schema_v4.py` | 8 | PASS |
| `tests/unit/curriculum/test_chapter_management.py` | 5 | PASS |
| `tests/unit/curriculum/test_syllabus_review_api.py` | 4 | PASS |
| `tests/integration/test_ingestion_canonical_mapping.py` | 2 | PASS |
| `tests/unit/curriculum/test_jee_canonical_coverage.py` | 9 | PASS |
| Full Curriculum Regression Suite (`tests/unit/curriculum/` + integration) | **341** | **ALL PASS (0 FAILURES)** |

### 9.2 Code Quality & Linting
```bash
ruff check curriculum/ backend/routes/curriculum.py backend/services/curriculum_service.py backend/services/knowledge_build_service.py tests/unit/curriculum/ tests/integration/test_ingestion_canonical_mapping.py
```
**Result:** `All checks passed!` (0 errors).

---

## 10. External Cross-Team Handoffs

### Person 3 (AI Tutor & Learner Model)
- **Status:** 100% backward compatible.
- **Contract:** All 62 simulator concept IDs in `concepts.csv` map decisively to active or legacy-retained canonical concepts.
- **Handoff Action:** When Person 3 is ready to train AKT models on the 27 new granular concepts, they can ingest the Schema v4 CSV exported via `python -m curriculum.schema_v4 --export storage/jee_v4.csv`.

### Person 4 (Frontend / Teacher UI)
- **Status:** Backend APIs fully exposed and verified via TestClient.
- **Contract:** Person 4 can connect the Teacher Curriculum Management UI directly to the `/api/curriculum/chapters`, `/api/curriculum/concepts/{id}/chapter`, and `/api/curriculum/syllabus/*` endpoints as documented in Section 8.

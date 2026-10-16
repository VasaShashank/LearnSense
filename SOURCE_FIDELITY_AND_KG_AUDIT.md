# LearnSense — Source Fidelity, Knowledge Representation, and Adaptive Learning Audit

**Date:** 2026-10-14  
**Scope:** Ingestion Pipeline, PPTX/PDF Extraction Fidelity, Phase 2 Knowledge Graph Builder, Evidence Provenance, Grounded Tutoring & Learning Experience.

---

## 1. Current Extraction Pipeline and Execution Paths

LearnSense processes educational materials through an authoritative, deterministic, multi-stage pipeline:

```
[Uploaded File (PDF, PPTX, DOCX, TXT, MD, Image)]
         │
         ▼
[Phase 5: Input Validation] (phase5.validation.input_validator.InputValidator)
         │
         ▼
[Format Normalisation] (ingestion.document_formats.to_structured_document)
   ├── PDF: EscalationRouter (Native PyMuPDF -> OCR -> Layout -> Tables -> Math -> VLM)
   ├── PPTX: python-pptx Native Presentation Parser
   ├── DOCX: python-docx Native Document Parser
   └── Images/Text: Normalised via PyMuPDF/synthetic PDF pagination
         │
         ▼
[StructuredDocument] (Contract: pages, blocks with bbox, reading order, roles, outline)
         │
         ▼
[Phase 2: Educational Knowledge Representation (EKR)] (phase2.pipeline.runner.Phase2PipelineRunner)
   ├── Stage 1: Text & Block Normalisation (stage1_normalize.py)
   ├── Stage 2: Document Profile & Context Detection (stage2_context.py)
   ├── Stage 3: Educational Unit Segmentation & Role Classification (stage3_segment.py)
   ├── Stage 4: Candidate Extraction - Concepts, Mentions, Skills, Formulas, Definitions (stage4_candidates.py)
   ├── Stage 5: Entity Resolution, Acronym Mapping & Canonicalisation (stage5_resolution.py + semantic_entity_resolver.py)
   ├── Stage 6: Object Assembly (stage6_object_assembly.py)
   ├── Stage 7: Relationship Extraction & Prerequisite Verification (stage7_relationships.py)
   ├── Stage 8: Graph Construction & DAG Cycle Prevention (stage8_graph.py)
   └── Stage 9: Semantic Quality Control & Packaging (stage9_qc.py)
         │
         ▼
[Semantic Topic & Prerequisite Extractor] (phase2.pipeline.semantic_topic_extractor.SemanticTopicExtractor)
   ├── LLM Mode (Live): Extracts pedagogical topic clusters & directed dependencies
   └── Deterministic Mode (Offline/Mock): Section-based curriculum progression & acyclic prerequisite graph
         │
         ▼
[Phase 3: LearningContext Adaptation] (phase3.knowledge.phase2_adapter.Phase2Adapter)
   └── Persisted via LearningContextRepository and DocumentStorage
```

---

## 2. PDF/PPTX Extraction Failures and Root Causes

| Format | Observed Defect | Root Cause in Code | Impact on Knowledge Graph |
|---|---|---|---|
| **PPTX** | **All presentation tables are silently dropped** | `ingestion/document_formats.py:406` checks `if not shape.has_text_frame: continue`. In `python-pptx`, tables have `shape.has_table == True` while `shape.has_text_frame == False`. | Matrix data, comparison tables, and parameter specifications in slides are missing from the EKR. |
| **PPTX** | **Speaker notes are ignored** | `pptx_to_structured_document` only iterates `slide.shapes` and does not read `slide.notes_slide.notes_text_frame`. | Lecturer explanations, definitions, and commentary in slide notes are completely omitted. |
| **PPTX** | **Hardcoded bounding boxes & slide canvas** | Dimensions hardcoded to `960x540`; blocks assigned synthetic sequential Y coordinates rather than reading `shape.left.pt`, `top.pt`, `width.pt`, `height.pt`. | Visual citations cannot accurately highlight source shapes on the slide. |
| **PDF** | **Single-occurrence definitions dropped** | `stage4_candidates.py:33` enforces `MIN_TERM_OCCURRENCES = 2` without checking if a candidate has an explicit definition in `res.harvested_definitions`. | Key terms introduced and defined once in a lecture or section are omitted from the concept list. |
| **EKR** | **Harvested definitions discarded in Stage 5** | `stage5_resolution.py` creates `Concept` objects with `description=None` without checking `candidates.harvested_definitions`. | Concepts lack textual definitions in the knowledge representation even when the source explicitly defines them. |

---

## 3. VLM Configuration, Model Compatibility and Routing Diagnosis

1. **Routing Strategy (`ingestion/router.py`)**:
   - `auto` (default): Routes through `PageInspector`. Only pages flagged with `needs_vlm` (complex flowcharts, visual diagrams, dense schematics) escalate to the VLM.
   - `disabled`: Skips VLM entirely; executes PyMuPDF native text extraction with Tesseract OCR fallback.
   - `always`: Escalates all pages to VLM.
2. **Model Compatibility (`adapters/vlm_adapter.py`)**:
   - Supports Gemini (`gemini-1.5-flash`, `gemini-2.0-flash`) and OpenAI (`gpt-4o`, `gpt-4o-mini`).
   - Graceful Degradation: If API keys are absent or network requests time out, the system falls back to native text extraction without crashing the pipeline.
3. **Diagnosis**:
   - All 8 unit test suites in `tests/unit/test_vlm_routing.py` pass cleanly.
   - Caching operates via SHA256 image hashes, preventing duplicate API expenses.
   - VLM blocks contain valid `extraction_method="VLM"` metadata and source coordinates.

---

## 4. Source Provenance and Canonical Representation Assessment

- **Block Identity**: Every block carries a unique `block_id` (`blk_p{page:04d}_{type}_{order:04d}`).
- **Evidence Binding**: Evidence spans in `phase2.models.Evidence` store `block_id`, `span: TextSpan(start, end)`, `excerpt`, and `level: EvidenceLevelEnum`.
- **Traceability**: Concepts and Relationships store explicit lists of `evidence_ids`.
- **Integrity Gap Identified**: When PPTX blocks used synthetic Y coordinates, citations pointed to the right slide but approximate pixel positions. Binding real shape geometry (`shape.left.pt`, `shape.top.pt`) restores visual fidelity.

---

## 5. Knowledge Graph Concept and Relationship Quality Assessment

- **Concept Precision**:
  - Filtered against 100+ document boilerplate stopwords (`STOPWORDS`), discourse markers (`DISCOURSE_WORDS`), and furniture terms (`_FURNITURE_WORDS`).
  - Plural normalization folds variants (`derivative` / `derivatives`) to the canonical frequent term.
- **Relationship Quality**:
  - Direct syntactic dependency mining: detects `"requires"`, `"depends on"`, `"prerequisite for"`, `"builds on"`, `"relies on"`, and `"recall X before studying Y"`.
  - Negation & Hedging filter: phrases such as `"no prior knowledge"`, `"optional"`, `"does not require"` are excluded to prevent false prerequisite edges.
  - DAG Enforcement: Cycle detection using DFS (`has_directed_path`) rejects cyclic prerequisite links, ensuring valid curriculum sequencing.

---

## 6. Grounded Retrieval and Conversational Tutoring Assessment

- **Retrieval Engine (`phase3/retrieval.py`)**:
  - BM25 evidence retrieval over canonical structured document blocks.
  - Retrieves exact slide/page references and text excerpts.
- **Grounding Verification**:
  - `tests/unit/test_tutor_grounding.py` verifies:
    - Citations have real source references.
    - Novice/Advanced prompt adaptations.
    - Defense against prompt injection attempts.
  - Zero hallucinations of non-extracted facts when evidence is absent.

---

## 7. Frontend Interaction Implementations Relevant to Learning Workflow

1. **Course Workspace**: Supports upload and status monitoring across PDF, PPTX, DOCX, and images.
2. **Interactive Concept Map & Topic Clusters**:
   - Visualizes nodes and directed prerequisite arrows.
   - Encompasses concepts in macro pedagogical territories (`Foundations`, `Core Principles`, `Advanced Applications`) with `TopicClusterNode.tsx`.
   - Connects section outline nodes via `SubheadingNode.tsx` for hierarchical DAG navigation.
3. **Teaching Optimizer & Teacher Dashboard**:
   - Institutional class selection and cohort monitoring.
   - Dynamic concept-level mastery cards with human-readable labels instead of raw IDs.
   - Standalone educator support with FERPA-compliant de-identification (`Student #104`).
4. **Citation Inspection & Contextual Tutoring**:
   - When clicking a source citation in tutor chat, the exact slide/page number and excerpt are displayed.
5. **Atlas Intelligence & Canvas Annotations**:
   - Interactive local annotations, pins, and graph metrics computed directly on canvas.

---

## 8. Existing Features to Preserve

- Complete 9-stage Phase 2 pipeline contracts (`phase2/pipeline/stage1_normalize.py` through `stage9_qc.py`).
- Bayesian Knowledge Tracing (BKT) learner state updates (`bkt_model.py`).
- Strict schema validation and typed error handling in `phase3.errors`.
- Semantic Entity Resolution with synonym and acronym mapping.
- Institutional RBAC (Admin/Teacher/Learner) and Cohort analytics.

---

## 9. Ranked Improvements & Acceptance Criteria

| Rank | Improvement | Dependencies | Complexity | Risk | Acceptance Criteria |
|---|---|---|---|---|---|
| **P0** | **Native PPTX Tables & Speaker Notes Extraction** | `python-pptx` | Low | Low | PPTX tables extracted as `BlockTypeEnum.TABLE` with markdown representation; speaker notes extracted as `role="notes"`. Real shape coordinates preserved. |
| **P0** | **Preserve Defined Concepts in Stage 4** | None | Low | Low | Candidates with harvested definitions (`X is defined as Y`) are not dropped by `MIN_TERM_OCCURRENCES = 2`. |
| **P0** | **Bind Definitions to Concepts in Stage 5** | None | Low | Low | Harvested definitions populate `concept.description` and emit `EvidenceKindEnum.DEFINITION` evidence. |
| **P1** | **Table Cell Concept Mention Extraction** | P0 | Medium | Low | Concepts mentioned in structured table rows/columns are recognized as candidate mentions. |
| **P2** | **Slide Bounding Box Visual Citation Verification** | P0 | Low | Low | Citations from PPTX slides contain accurate proportional bounding boxes. |

---

## 10. Smallest High-Value Implementation Batch (Executing Now)

1. **`ingestion/document_formats.py`**:
   - Add PPTX table extraction: parse `shape.has_table`, format cell content into readable markdown and structured text, tag as `BlockTypeEnum.TABLE`.
   - Add PPTX speaker notes extraction: check `slide.notes_slide.notes_text_frame`, extract notes with `role="speaker_notes"`.
   - Extract real shape bounding boxes in points (`left.pt`, `top.pt`, `width.pt`, `height.pt`) and actual slide width/height (`presentation.slide_width.pt`, `slide_height.pt`).
2. **`phase2/pipeline/stage4_candidates.py`**:
   - Exclude terms that have an explicit definition in `res.harvested_definitions` from the `MIN_TERM_OCCURRENCES = 2` exclusion.
3. **`phase2/pipeline/stage5_resolution.py`**:
   - Match harvested definitions against canonical concept names/aliases, populate `concept.description`, and generate `EvidenceKindEnum.DEFINITION` evidence.
4. **Validation**:
   - Write comprehensive unit tests in `tests/unit/test_pptx_fidelity.py` and run full regression test suites.

---

## 11. Multi-Format Source Fidelity Overhaul & Verification Results

All improvements across **all source materials (PDF, PPTX, DOCX, Markdown/Text)** have been implemented, hardened against static no-fallback AST guards, and verified:

1. **Multi-Format Extraction Fidelity**:
   - **Microsoft Word (.docx)**: Tables converted to `BlockTypeEnum.TABLE` markdown grids; heading hierarchy and paragraphs preserved.
   - **Microsoft PowerPoint (.pptx)**: Tables extracted with cell grids, speaker notes extracted with `role="speaker_notes"`, canvas bounding boxes mapped with point dimensions.
   - **Markdown / Plain Text (.md, .txt)**: Colon definitions (`Term: Definition`) and glossaries harvested alongside copular statements.
   - **Prose Mining**: Lowercase multi-word domain concepts (e.g. `neural network`, `dynamic programming`) captured via sliding-window n-grams with verbatim text span resolution.

2. **Knowledge Graph Grounding & Provenance**:
   - Definitions bound to `concept.description` and emitted as `EvidenceKindEnum.DEFINITION_PATTERN` with character spans.
   - Rich relationship extraction enabled for `PREREQUISITE_OF`, `IS_A`, `INSTANCE_OF`, and `PART_OF`.
   - Semantic Topic Extractor preserves and merges Stage 7 mined relationships and definitions, connecting concepts into a complete DAG.

3. **Golden Evaluation Benchmarking**:
   - [`evaluation/phase2_eval.py`](file:///c:/Users/basav/Downloads/MAIN%20EL%205TH%20SEM/LearnSense/evaluation/phase2_eval.py) expanded with concept, definition, and relationship recall metrics.
   - [`tests/unit/test_phase2_multi_format_eval.py`](file:///c:/Users/basav/Downloads/MAIN%20EL%205TH%20SEM/LearnSense/tests/unit/test_phase2_multi_format_eval.py) benchmark suite passing across Word, PowerPoint, and Markdown/PDF.

4. **Test Suite Status**:
   - `test_no_fallbacks.py`: 4 passed (zero bare excepts or swallowed exceptions).
   - Full regression suite: **229 passed in 41.68s** (100% green).
   - Frontend production build: **Passed in 2.41s** (0 TypeScript/Vite errors).

# LearnSense / TAPROOT — Phase 2 Implementation Plan & Architecture
## NLP + Educational Knowledge Representation (EKR)

---

## 1. Role & System Boundary
Phase 2 bridges raw structural document ingestion and higher-level adaptive learning:
```
StructuredDocument (Phase 1)
           ↓
Educational Understanding & Entity Resolution (Phase 2 Stages 1–6)
           ↓
Prerequisite Graph & DAG Construction (Phase 2 Stages 7–8)
           ↓
Educational Knowledge Representation (EKR) & Topic Clusters (Phase 2 Stage 9)
           ↓
LearningContext & Knowledge Tracing (Phase 3 & Phase 4)
```

---

## 2. Core 9-Stage Pipeline Architecture

1. **Stage 1: Text & Block Normalization (`stage1_normalize.py`)**:
   - Cleans ligatures, tokenizes educational text, unifies Unicode characters, and tags reading orders.
2. **Stage 2: Document Context & Section Detection (`stage2_context.py`)**:
   - Ingests document outline hierarchy, heading levels (H1–H3), and slide titles.
3. **Stage 3: Educational Unit Segmentation & Role Classification (`stage3_segment.py`)**:
   - Classifies semantic block roles: `definition`, `theorem`, `formula`, `worked_example`, `exercise`, `summary`, and `key_point`.
4. **Stage 4: Candidate Extraction (`stage4_candidates.py`)**:
   - Mines concept mentions, Bloom's skills, definitions, acronyms, and formulas.
   - Enforces zero-drop for single-occurrence defined concepts (`harvested_definitions`).
5. **Stage 5: Entity Resolution & Canonicalization (`stage5_resolution.py`)**:
   - Resolves synonyms, resolves acronym expansions, binds explicit definitions to `concept.description`, and merges surface variants.
6. **Stage 6: Knowledge Object Assembly (`stage6_object_assembly.py`)**:
   - Assembles canonical `Concept`, `Skill`, and `AssessmentItem` data models with evidence provenance links.
7. **Stage 7: Relationship Extraction (`stage7_relationships.py`)**:
   - Mines prerequisite links (`PREREQUISITE_OF`), hierarchical links (`IS_A`, `PART_OF`), and conceptual links with confidence scoring.
8. **Stage 8: Graph Construction & DAG Cycle Prevention (`stage8_graph.py`)**:
   - Tarjan's Strongly Connected Components (SCC) algorithm identifies all circular dependencies.
   - Cycle-breaking heuristics remove weakest feedback edges, guaranteeing a strict Directed Acyclic Graph (DAG).
9. **Stage 9: Quality Control & Packaging (`stage9_qc.py`)**:
   - Performs schema verification, graph connectivity checks, and serializes the authoritative EKR artifact.

---

## 3. Semantic Topic Extractor & Subheading Navigation
- **Semantic Topic Extractor (`phase2/pipeline/semantic_topic_extractor.py`)**:
  - Automatically synthesizes higher-level pedagogical topic clusters (e.g. *Foundational Concepts*, *Core Theory*, *Advanced Applications*).
  - In Live Mode (Groq LLM), synthesizes enriched topic territories.
  - In Offline/Deterministic Mode, derives clusters directly from document outline headings.
  - Integrates with frontend `TopicClusterNode` and `SubheadingNode` for structured Atlas navigation.

---

## 4. Multi-Format Fidelity Extensions
- **PowerPoint (`.pptx`)**: Tables extracted with full cell grids, speaker notes extracted with `role="speaker_notes"`, canvas bounding boxes mapped with real slide dimensions.
- **Word (`.docx`)**: Semantic table extraction and heading level preservation.
- **Markdown / Plain Text (`.md`, `.txt`)**: Colon definitions and glossary parsing.
- **Image Diagrams (`.png`, `.jpg`)**: Optical text extraction with layout preserving synthetic coordinates.

---

## 5. Evaluation & Verification
- Evaluation suite in `evaluation/phase2_eval.py` measures concept precision, definition recall, and relationship edge validity against golden curriculum baselines.

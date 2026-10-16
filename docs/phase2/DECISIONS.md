# Phase 2 Design Decisions & Contract Notes

## 1. Consumed Phase 1 Schema Version
- **Schema Version:** `1.0.0`
- **Pipeline Version:** `2026.09.0`
- **Supported Formats:** PDF, PPTX, DOCX, PNG, JPG, JPEG, TXT, MD.

---

## 2. Identified Field Gaps in Phase 1 & Multi-Format Resolution

| Field / Format | Observed Issue | Phase 2 Production Resolution |
|---|---|---|
| **Inline emphasis spans (bold/italic)** | Not explicitly in Phase 1 `DocumentBlock` | Regex detection over raw text when needed; optional styling field. |
| **Heading level / list nesting** | Present in `SectionNode` / `BlockTypeEnum.LIST_ITEM` | Infer level from `SectionNode.level` or list block position. |
| **Equation number & LaTeX/MathML** | Block type `EQUATION`, text raw in `BlockContent` | Parse LaTeX/MathML from raw content text; equation number extracted via regex. |
| **PPTX Tables** | Missing if only checking `has_text_frame` | Explicitly inspect `shape.has_table`; extract cell grid into Markdown table block. |
| **PPTX Speaker Notes** | Ignored in naive slide parsers | Extract `slide.notes_slide.notes_text_frame` with semantic role `speaker_notes`. |
| **DOCX Tables** | Unstructured table blocks | Parse XML table elements into structured row/cell records. |
| **Single-occurrence terms** | Dropped by `MIN_TERM_OCCURRENCES = 2` | Exclude terms from dropping if they have a harvested definition (`harvested_definitions`). |
| **Harvested Definitions** | Discarded in naive canonicalization | Match definitions to canonical concepts and store in `concept.description`. |

---

## 3. Decision Log

- **Q1 (Schema Version):** Consuming Phase 1 schema `1.0.0`. Additive extensions permitted for table grids and speaker notes.
- **Q2 (Semantic Roles):** Implementing 15 V1 roles: `definition`, `explanation`, `example`, `worked_example`, `theorem`, `formula`, `procedure`, `learning_objective`, `summary`, `key_point`, `exercise`, `question`, `answer`, `prerequisite_statement`, `other`.
- **Q3 (Concept Scope):** `educational` if defined, emphasized, or recurring; `mentioned_only` if named briefly.
- **Q4 (Skill Definition):** Tuple `(action, concepts, condition)`. Actions: `recall`, `identify`, `calculate`, `solve`, `derive`, `apply`, `compare`, `classify`, `explain`, `interpret`, `prove`, `construct`.
- **Q5 (Deterministic IDs):** Deterministic SHA-256 hashes generated from document ID and normalized canonical strings.
- **Q6 (DAG Enforcement):** Use Tarjan's Strongly Connected Components (SCC) algorithm to detect cycles, then break feedback edges deterministically based on confidence scoring and document reading order.
- **Q7 (Macro Topic Clusters):** Automatically cluster granular concepts into macro pedagogical territories (`Foundations`, `Core Principles`, `Advanced Applications`) using `SemanticTopicExtractor` to power frontend Atlas grouping.

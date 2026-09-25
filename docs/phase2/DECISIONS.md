# Phase 2 Design Decisions & Contract Notes

## 1. Consumed Phase 1 Schema Version
- **Schema Version:** `1.0.0`
- **Pipeline Version:** `2026.09.0`

## 2. Identified Field Gaps in Phase 1 & Fallback Strategy

| Assumed Field | Phase 1 Status | Phase 2 Fallback Strategy |
|---|---|---|
| Inline emphasis spans (bold/italic) | Not explicitly in Phase 1 `DocumentBlock` | Optional heuristic / Regex detection over raw text if needed; optional field. |
| Heading level / list nesting | Present in `SectionNode` / `BlockTypeEnum.LIST_ITEM` | Infer level from `SectionNode.level` or list block position. |
| Equation number & LaTeX/MathML | Block type `EQUATION`, text raw in `BlockContent` | Parse LaTeX/MathML from raw content text; equation number extracted via regex fallback. |
| Table header cell distinction | `structured_data` dict in `BlockContent` | Fall back to row 0 / first line parsing if structured table cells absent. |
| Caption ↔ Figure/Table linkage | `DocumentAsset.caption_block_id` present | Use asset mapping first, proximity fallback second. |
| Span-level language tags | Block level `language` present | Default span language to block language unless tagged by NLP tokenizer. |
| Reading-order confidence | `reading_order` int present, confidence at block level | Use block confidence as upper limit for reading order certainty. |

## 3. Decision Log
- **Q1 (Schema Version):** Consuming Phase 1 schema `1.0.0`. Minor additive versions permitted.
- **Q2 (Semantic Roles):** Implementing 15 V1 roles: `definition`, `explanation`, `example`, `worked_example`, `theorem`, `formula`, `procedure`, `learning_objective`, `summary`, `key_point`, `exercise`, `question`, `answer`, `prerequisite_statement`, `other`.
- **Q3 (Concept Scope):** `educational` if defined/emphasized/recurring; `mentioned_only` if named briefly.
- **Q4 (Skill Definition):** Tuple `(action, concepts, condition)`. Actions: `recall`, `identify`, `calculate`, `solve`, `derive`, `apply`, `compare`, `classify`, `explain`, `interpret`, `prove`, `construct`.
- **Q5 (IDs):** Deterministic SHA-256 hashes generated from document ID and normalized canonical strings.

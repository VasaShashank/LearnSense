# TAPROOT — Phase 1 Master Implementation Plan & Completion Specification
## Phase 1A (Core Ingestion) + Phase 1B (Educational Content) + Phase 1C (Robustness & Security)
### CPU-First Educational PDF Ingestion & Structuring Pipeline

---

## 0. Executive Implementation Status Summary

> **Implementation Status: COMPLETE (100% Implemented & Verified)**
> All Phase 1A, Phase 1B, and Phase 1C capabilities defined in this specification have been fully implemented, integrated, and verified using automated test suites.

### Key Delivered Components
1. **Canonical Schema (`schemas/document.py`)**: Complete Pydantic V2 implementation of `StructuredDocument` matching Section 25.
2. **Storage & Database (`storage/store.py`, `storage/db.py`)**: Content-addressed filesystem store and SQLite WAL database manager with exact-hash SHA-256 caching.
3. **PDF Validation & Repair (`ingestion/validator.py`)**: File size/page count capping, magic byte check, password protection policy, and automatic PyMuPDF xref repair.
4. **Cheap Page Inspection (`ingestion/inspector.py`)**: 150 DPI preview rendering, NumPy ink density calculation, character/garbage counting, image coverage ratio, vector path counting, and `page_type` classification (`native`, `scanned`, `hybrid`, `blank`).
5. **Coordinate Normalization (`ingestion/coordinate.py`)**: Standardizes bounding boxes across engines, CropBox offsets, and rotation flags (0°, 90°, 180°, 270°) into top-left points canonical space `[x0, y0, x1, y1]`.
6. **Native Text Extractor (`extraction/text.py`)**: PyMuPDF span extraction with NFC Unicode normalization, ligature replacement (`ﬁ` -> `fi`), subscript/superscript detection, and line-end hyphenation rejoining.
7. **Layout Analyzer (`extraction/layout.py`)**: Single/multi-column detection, reading order sorting, document body font size mode calculation, and heading (H1/H2/H3)/paragraph/list/code classification.
8. **OCR Engine Adapter (`adapters/tesseract_adapter.py`, `extraction/ocr.py`)**: OpenCV image deskewing, Otsu adaptive thresholding, Tesseract 5 C++ execution (`-l eng+hin`), and Devanagari/Latin script block language classification.
9. **Table Extractor (`extraction/tables.py`)**: Native vector matrix grid extraction via `pdfplumber` with fallback image crop asset preservation (`TABLE_RECONSTRUCTION_FAILED` warning).
10. **Math Extractor (`extraction/math.py`)**: Math symbol density scanning, inline vs. display equation isolation, LaTeX formatting, and equation crop asset fallback (`MATH_UNPARSED` warning).
11. **Figure Extractor (`extraction/figures.py`)**: Raster image extraction, OpenCV vector path diagram clustering, decorative icon filtering, and `Figure X` caption association.
12. **Educational Structure Tagger (`extraction/structure.py`)**: Structural tagging for Table of Contents (TOC), Glossaries, Bibliographies, Footnotes, Sidebars, Exercises, and Worked Examples.
13. **Security Sandbox (`security/sandbox.py`)**: Process CPU/memory resource limits, off-page and invisible white-on-white text detection (`HIDDEN_TEXT_DETECTED`), and prompt injection instruction pattern scanner (`POSSIBLE_PROMPT_INJECTION`).
14. **Pass B Aggregator (`ingestion/pass_b.py`)**: Cross-page repeated header/footer/page_number classification, cross-page sentence continuity linking, outline `SectionNode` tree building, and title inference.
15. **Escalation Router & Pipeline Coordinator (`ingestion/router.py`, `ingestion/pipeline.py`)**: 4-rung progressive processing escalation ladder orchestrating end-to-end PDF processing from raw bytes to schema-valid JSON.
16. **FastAPI Web Server (`backend/app.py`, `backend/routes/documents.py`)**: REST API endpoints supporting PDF upload, status polling, structured document retrieval, page streaming, and asset downloading.

---

## 1. Executive Summary

TAPROOT is an educational AI system designed to transform raw, heterogeneous study materials into structured, machine-readable representations. Phase 1 defines the complete document ingestion pipeline, converting unstructured, variable-quality educational PDFs (lecture notes, textbooks, scanned handouts, slide decks, and question papers) into a canonical `StructuredDocument` format.

This document merges the preliminary Phase 1 design specifications (Appendix A) and the detailed architecture review (Appendix B) into a single, concrete, implementation-ready engineering master plan. Phase 1 is built around a single core rule:
> **Detect → Route → Extract → Preserve → Quality Check → Produce StructuredDocument**
> *Never silently discard information. Never fabricate information. Never convert low-confidence extraction into trusted content.*

The pipeline is strictly designed to execute locally on student-grade, CPU-only hardware (8–16 GB RAM, no dedicated GPU). Heavy ML vision models are avoided or relegated to optional cloud/Colab evaluation, prioritizing fast, deterministic rule-based and PDF-native extraction heuristics, backed by lightweight CPU-friendly OCR and layout tools.

---

## 2. Strict Phase 1 Scope

Phase 1 operates strictly as an **ingestion and structuring system**, establishing a clean boundary with Phase 2 (NLP, Knowledge Representation, and Reasoning).

```
[ Uploaded PDF ]
      │
      ▼
Phase 1: Validation ──► Inspection ──► Routing ──► Extraction ──► Preservation ──► Quality Check ──► StructuredDocument
      │
      ▼
==============================================================================================================
PHASE 1 / PHASE 2 BOUNDARY: StructuredDocument JSON Output
==============================================================================================================
      │
      ▼
Phase 2: Concept Extraction, Knowledge Graph Construction, Prerequisite Trees, Question Generation, Personalization
```

### Explicit Non-Scope (Strictly Prohibited in Phase 1)
- Semantic concept extraction and knowledge graph construction
- Prerequisite graph generation or educational difficulty scoring
- Question/quiz generation and distractor generation
- Student profiling, mastery tracking, or personalized learning paths
- LLM-based educational interpretation or summarization
- Natural language reasoning or automated grading

---

## 3. Phase 1A Scope — Core Document Ingestion

Phase 1A provides the baseline ingestion functionality for clean digital educational PDFs:

1. **Upload & Persistence**: Ingest PDF, assign immutable `document_id`, compute SHA-256 hash, and store original file unchanged.
2. **PDF Validation**: Detect corrupted, repairable, password-protected, encrypted, or invalid PDFs; enforce basic file size and page count limits.
3. **Cheap Page Inspection**: Inspect physical page metrics (`width`, `height`, `orientation`, `rotation`, native text presence, image coverage, vector density, font encoding validity).
4. **Native Text & Metadata Extraction**: Extract native PDF text layer preserving raw characters, normalized Unicode (NFC), superscripts/subscripts, basic line-hyphenation rejoining, and font metrics.
5. **Layout & Reading Order**: Identify single/multi-column layouts, headings, body paragraphs, lists, code blocks, and establish deterministic reading order using spatial bounding boxes.
6. **Repeated Content & Page Identity**: Differentiate physical `page_index` (0-based) from printed `page_label` (`iv`, `12`, `3-A`). Classify headers, footers, page numbers, and watermarks without deleting them.
7. **Blank & Near-Blank Page Handling**: Detect blank/near-blank pages via rendered pixel ink density rather than text-layer absence.
8. **Section Hierarchy & Outline**: Build a document section tree using font statistics, numbering patterns (`1.2.3`), and embedded PDF bookmarks.

---

## 4. Phase 1B Scope — Educational Content & Complex PDFs

Phase 1B extends Phase 1A to handle common complex educational layouts and scanned materials:

1. **Scans & OCR**: Region-level and page-level routing to CPU OCR engine (Tesseract 5) when native text is missing, garbled, or low-quality.
2. **Multilingual Processing**: Support English, Hindi, and mixed English+Hindi pages with block-level language tagging.
3. **Table Extraction**: Native table extraction via rule-based geometry heuristics (`pdfplumber`/`Camelot`) with OCR fallback for scanned tables, outputting structured matrix JSON.
4. **Mathematical Content**: Detection of inline math, display equations, chemical formulas, and equation numbers; preserve unparsed math as image assets while extracting high-confidence LaTeX.
5. **Figures & Visual Assets**: Extract raster images and detect vector diagram clusters; associate assets with figure/table captions.
6. **Educational Structure Tagging**: Structurally classify Table of Contents (TOC), glossaries, bibliographies, indexes, footnotes, sidebars, callout boxes, worked examples, exercises, and code listings.
7. **PDF-Native Enhancements**: Preserve PDF bookmarks, named destinations, internal hyperlinks, external URLs, and user annotations (highlights, sticky notes).

---

## 5. Phase 1C Scope — Robustness, Security & Operational Hardening

Phase 1C hardens the 1A+1B system for reliable, safe local operation:

1. **PDF Repair & Edge Handling**: Automatic recovery of damaged xref tables/trailers (`mutool` / PyMuPDF repair); isolated page failure handling (`completed_with_warnings`).
2. **Security & Sandboxing**: Execute untrusted PDF parsers in restricted worker processes with CPU, memory, pixel-render, and execution time limits. Disable PDF JavaScript, launch actions, and embedded executable files.
3. **Adversarial Content Defense**: Detect hidden/off-page text, white-on-white text, and prompt-injection instructions (`POSSIBLE_PROMPT_INJECTION` warning).
4. **Engine Adapter & Escalation Ladder**: Decouple extraction through unified adapter interfaces with multi-rung fallback logic.
5. **Idempotency & Stage-Level Caching**: Reuse previous page/stage outputs based on SHA-256 + pipeline version + config hash.
6. **Resource Guardrails & Progress Streaming**: CPU RAM capping (streaming page-by-page processing), background state orchestration, and structured observability logging.

---

## 6. Hardware Constraints & Primary Design Principle

### Target Machine Specification
- **CPU**: Intel Core i5/i7 (8th Gen+) or AMD Ryzen 5/7, 4 to 8 cores.
- **RAM**: 8 GB to 16 GB system memory.
- **GPU**: None (Intel UHD / Integrated graphics only).
- **Storage**: SSD with ~10 GB free space.

### Core Architecture Rules
1. **Zero CUDA/GPU Dependency**: All baseline Phase 1 capabilities MUST run on CPU.
2. **Low RAM Footprint**: Never load an entire multi-hundred-page PDF into memory. Process page-by-page or in small streaming batches.
3. **Lightweight First**: Prefer fast rule-based C-extensions (PyMuPDF, OpenCV C++) over deep neural networks.

---

## 7. Final Technology Stack

| Capability | Chosen Tool / Library | Reason for Selection | CPU Feasibility & Resource Usage | Fallback |
| :--- | :--- | :--- | :--- | :--- |
| **Backend API** | FastAPI (Python 3.11) | Lightweight, async support, fast execution, native Pydantic validation. | Peak RAM: ~50 MB. Negligible CPU footprint. | Flask |
| **PDF Parsing & Rendering** | PyMuPDF (`fitz` v1.23+) | Extremely fast C-backed parser, excellent font/vector/coordinate access, fast rendering. | ~20–50 MB RAM per page. ~15ms render per page. | `pdfplumber` / `pypdf` |
| **PDF Repair** | `pymupdf` / `pdfminer.six` | Built-in xref table and page tree reconstruction capabilities. | Instant execution (<100ms). | Reject with `CORRUPTED` |
| **OCR Engine** | Tesseract 5 (`pytesseract`) | Mature open-source C++ OCR, strong CPU performance, native Hindi (`hin`) + English (`eng`) support. | ~100–300 MB RAM per thread. 0.5s–2.0s per page. | Preserve image + warning |
| **Layout Heuristics** | PyMuPDF geometry + `pdfminer.six` layout analyzer | Rule-based column detection, bounding-box grouping, font-hierarchy scoring. Fast on CPU. | <20 MB RAM. <10ms per page. | Fallback reading-order sort |
| **Table Extraction** | `pdfplumber` + `Camelot-py` (Lattice/Stream) | Native vector line and whitespace grid analysis for structured table extraction. | ~40 MB RAM. 50–200ms per table. | Crop table image asset + OCR fallback |
| **Math Detection** | Rule-based font/symbol scan + vector regex | Identifies math symbols (Unicode math blocks, `cmr`/`cmsy` fonts) & bounding boxes natively. | <10 MB RAM. <5ms per page. | Preserve region as image |
| **Math Extraction** | Light CPU LaTeX parser / `pix2tex` (ONNX quant) | Converts isolated math crops into LaTeX on CPU when confidence > 0.85. | ~200 MB RAM (ONNX). ~0.3s per equation. | Crop math asset + `MATH_UNPARSED` warning |
| **Language Detection** | `fasttext-wheel` (compressed language model) | Extremely fast C++ bindings, 99%+ accuracy for English/Hindi block classification. | ~15 MB RAM (model file). <1ms per text block. | `langdetect` / default to `en` |
| **Vector Diagram Extraction** | OpenCV Python (`opencv-python-headless`) | Detects dense vector path bounding box clusters and extracts vector/raster figures. | ~30 MB RAM. <20ms per page. | Crop bounding box region |
| **Database & Queue** | SQLite (WAL mode) + Python `concurrent.futures` | Zero-dependency, lightweight, reliable job state tracking and caching without Redis/Celery. | <10 MB RAM. Zero background daemon overhead. | In-memory queue |
| **Storage** | Filesystem storage (SHA-256 directories) | Simple, transparent, inspectable, fast local file access. | Disk space bound by upload sizes. | N/A |

---

## 8. Model Selection & Specification

| Model Name / Artifact | Purpose | Size on Disk | CPU Feasibility | RAM Requirement | Execution Speed | Accuracy Benefit | Fallback Path | Selection Justification |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **Tesseract 5 TrainedData (`eng`, `hin`)** | Scanned text OCR & multilingual extraction | ~30 MB total (`eng.traineddata` + `hin.traineddata`) | **High** (Native C++) | ~100 MB | ~1.0 sec / page on CPU | High accuracy for standard Hindi & English scanned notes | Native text extraction or preserved page crop | Industry standard CPU OCR, easy OS package installation, fast execution. |
| **FastText Compressed Language Model (`lid.176.ftz`)** | Block-level language classification | ~917 KB | **High** (Native C++) | ~15 MB | <1 ms / block | Rapid multi-language identification on mixed pages | Default to `en` if confidence < 0.6 | Tiny memory footprint, instant CPU prediction, covers English and Hindi. |
| **LaTeX-OCR ONNX Quantized (`pix2tex-quant`)** | Math equation image to LaTeX conversion | ~45 MB (Quantized INT8) | **Medium** (CPU ONNX Runtime) | ~200 MB | ~0.3 sec / crop | Accurate LaTeX generation for complex display equations | Preserve math image asset + `MATH_UNPARSED` | Lightweight quantized model running on CPU ONNX Runtime without PyTorch GPU requirements. |

---

## 9. System Architecture

```
                                  +---------------------------------------+
                                  |            FastAPI Web API            |
                                  |   POST /documents, GET /status, etc.   |
                                  +-------------------+-------------------+
                                                      |
                                                      v
                                  +---------------------------------------+
                                  |         Storage & Job Engine          |
                                  |    Filesystem Store + SQLite DB       |
                                  +-------------------+-------------------+
                                                      |
                                                      v
                                  +---------------------------------------+
                                  |   Pass A: Parallel Page Processing    |
                                  +-------------------+-------------------+
                                                      |
        +---------------------------------------------+---------------------------------------------+
        |                                             |                                             |
        v                                             v                                             v
+---------------+                             +---------------+                             +---------------+
| Page Render & |                             | Text & Layout |                             | Asset & Region|
|   Inspection  |                             |   Extractor   |                             |   Detector    |
+-------+-------+                             +-------+-------+                             +-------+-------+
        |                                             |                                             |
        +---------------------------------------------+---------------------------------------------+
                                                      |
                                                      v
                                  +---------------------------------------+
                                  |            Escalation Router          |
                                  |  Native -> Layout -> OCR -> Specialized|
                                  +-------------------+-------------------+
                                                      |
        +---------------------------------------------+---------------------------------------------+
        |                                             |                                             |
        v                                             v                                             v
+---------------+                             +---------------+                             +---------------+
| Native Engine |                             | Tesseract OCR |                             | Table & Math  |
|  (PyMuPDF)    |                             | (Eng + Hin)   |                             |   Parsers     |
+-------+-------+                             +-------+-------+                             +-------+-------+
        |                                             |                                             |
        +---------------------------------------------+---------------------------------------------+
                                                      |
                                                      v
                                  +---------------------------------------+
                                  |          Page-Level QC Engine         |
                                  +-------------------+-------------------+
                                                      |
                                                      v
                                  +---------------------------------------+
                                  |    Pass B: Document Assembly Engine   |
                                  | Header/Footer, Section Tree, Links    |
                                  +-------------------+-------------------+
                                                      |
                                                      v
                                  +---------------------------------------+
                                  |   StructuredDocument Output (JSON)    |
                                  +---------------------------------------+
```

---

## 10. Detailed Processing Pipeline

### Phase 1 Pipeline Sequence
1. **Upload & Storage**: Client uploads PDF. SHA-256 hash generated. Initialized in SQLite DB as `queued`. Original PDF written to `documents/{id}/original/source.pdf`.
2. **Validation & Repair**:
   - Check magic bytes (`%PDF-`).
   - Attempt PyMuPDF load. If xref table corrupt, execute repair routine using PyMuPDF `clean()` / mutool repair.
   - Inspect password protection: reject if user-password required; proceed if owner-password restricted (with `OWNER_PASSWORD_RESTRICTED` warning).
3. **Pass A — Per-Page Streaming**:
   - For page `i` in `0..N-1`:
     - Render 150 DPI page preview image.
     - Execute Cheap Page Inspection (calculate ink ratio, character count, image area ratio, vector path count, font encoding flags).
     - Determine `page_type` (`native`, `scanned`, `hybrid`, `blank`, `near_blank`).
     - Route regions through Escalation Ladder (Native Extraction -> Rule Layout -> Tesseract OCR -> Table/Math Parsers).
     - Standardize all coordinates to Top-Left Points canonical space.
     - Run Page-Level Quality Control; attach page-level warnings.
     - Persist page result to `documents/{id}/intermediate/page_{index}.json`.
4. **Pass B — Document-Level Aggregation**:
   - Load all intermediate page JSON files.
   - Execute repeated content classification across pages (detect headers, footers, page numbers using position frequency analysis).
   - Build document section tree (`outline`) from font statistics, numbering patterns, and PDF bookmarks.
   - Connect cross-page continuity links (`continues_from`, `continues_to`).
   - Flag duplicate page candidates via visual perceptual hashing (phash) / text hashing.
   - Generate Document-Level Quality Summary.
   - Assemble final `StructuredDocument` JSON and save to `documents/{id}/structured/document.json`. Set job status to `completed` or `completed_with_warnings`.

---

## 11. Phase 1A Implementation Details

### Native Text & Geometry Extraction
Using PyMuPDF (`fitz`), text is extracted at the word and span level using `page.get_text("words")` and `page.get_text("dict")`.
- **Superscript / Subscript**: Detected using font flags (`flags & 2^0` for superscript, `flags & 2^1` for subscript) and relative font size drop (<80% baseline size).
- **Hyphenation Repair**: Rejoin end-of-line hyphens when a word is split across lines (`ac-` + `celeration` -> `acceleration`) if the combined word exists in dictionary or follows valid orthographic patterns.
- **Ligatures**: Convert Unicode ligatures (`ﬁ` -> `fi`, `ﬂ` -> `fl`, `æ` -> `ae`) using standard Unicode normalization (NFC).

### Bounding Boxes & Reading Order Algorithm
1. Extract all text blocks, table regions, and image regions on the page.
2. Group adjacent words into lines based on vertical overlap (>70% overlap) and horizontal spacing.
3. Classify column layout: compute vertical projection histogram of text line gaps.
4. For single-column: sort blocks top-to-bottom ($y_0$).
5. For multi-column: group blocks into column bands based on horizontal coordinates ($x_0, x_1$), then sort within each column top-to-bottom, and left-to-right across columns.
6. Sidebars and callouts outside primary column bands are assigned reading order indices after the adjacent body block.

### Heading Detection & Hierarchy Builder Algorithm
1. Calculate document-wide font size histogram across all native text blocks.
2. Assign baseline body font size $S_{body}$ as the statistical mode.
3. Compute score for each candidate block:
   $$\text{Score} = w_1 \cdot \left(\frac{S_{block}}{S_{body}}\right) + w_2 \cdot \text{IsBold} + w_3 \cdot \text{HasNumberingPattern} + w_4 \cdot \text{SpaceAbove}$$
   where $w_1=0.4, w_2=0.3, w_3=0.2, w_4=0.1$.
4. Assign heading levels:
   - $S_{block} \ge 1.8 \cdot S_{body} \rightarrow \text{Level 1 (H1)}$
   - $S_{block} \ge 1.4 \cdot S_{body} \rightarrow \text{Level 2 (H2)}$
   - $S_{block} \ge 1.15 \cdot S_{body} \text{ or Bold} \rightarrow \text{Level 3 (H3)}$
5. Reconcile heading hierarchy with regex numbering (`1.0`, `1.1`, `1.1.1`) and PDF outline bookmarks in Pass B.

---

## 12. Phase 1B Implementation Details

### OCR Strategy & Preprocessing
When `page_type` is `scanned` or region is routed to OCR:
1. Render target region at 300 DPI (`zoom = 300 / 72 = 4.166`).
2. Convert image to grayscale using OpenCV (`cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)`).
3. Apply adaptive deskewing using Radon transform / minAreaRect on ink contour angles (if angle $> 0.5^\circ$, rotate image).
4. Apply Otsu's adaptive thresholding for high contrast.
5. Execute Tesseract 5 via C API/pytesseract with parameters: `--psm 3` (automatic page segmentation) or `--psm 6` (uniform block), `-l eng+hin`.
6. Calculate confidence score from Tesseract block metadata. If confidence $< 0.60$, flag block as `ok_low_confidence` and attach `LOW_OCR_CONFIDENCE` warning.

### Multilingual Support (English + Hindi)
- Block-level language classification executed using `fasttext-wheel`.
- For text blocks containing Devanagari script (Unicode range `U+0900` to `U+097F`), assign `language = "hi"`.
- For Latin script, assign `language = "en"`.
- Mixed blocks tagged with `language = "hi+en"`.

### Table Pipeline
1. **Detection**:
   - Native: Identify grid intersection points from PDF vector drawing paths using `pdfplumber` / `Camelot`.
   - Scanned: OpenCV line detection using morphological operations (horizontal kernel `(25, 1)` and vertical kernel `(1, 25)`).
2. **Extraction**:
   - Reconstruct row/column matrix grid.
   - Extract text for each cell $(r, c)$. Handle row spans and column spans (`rowspan`, `colspan`).
   - If grid reconstruction fails or confidence $< 0.70$, extract bounding box as raster image asset `table_crop_{id}.png`, set status to `preserved_only`, and attach `TABLE_RECONSTRUCTION_FAILED` warning.

### Mathematics Pipeline
1. **Detection**: Scan for mathematical fonts (`CMEX`, `CMSY`, `MathJax`), math symbol density (summation, integral, Greek letters $\alpha, \beta, \theta$), or isolated equation numbers `(1.1)`.
2. **Inline vs Display**:
   - Inline Math: Symbol sequences within a standard body text line $\rightarrow$ preserve as inline text span with `is_math: true`.
   - Display Equation: Centered text block with vertical whitespace isolation or equation label $\rightarrow$ separate `equation` block.
3. **LaTeX Conversion**:
   - Native: Extract symbol mapping.
   - Scanned / Image Equation: Crop equation region. Run lightweight ONNX LaTeX-OCR model. If output confidence $> 0.85$, output LaTeX string. Otherwise, preserve equation crop asset and attach `MATH_UNPARSED` warning.

### Figures & Educational Structures
- **Raster Figures**: Extract embedded images via PyMuPDF `page.get_images()`. Filter out logos/icons (width or height $< 50$ px or repeated $>3$ pages).
- **Vector Diagrams**: Group dense vector drawing paths (path count $> 15$ in a 100x100 pt area) into a composite bounding box and render as PNG asset.
- **Caption Association**: Locate text blocks starting with `Figure X`, `Fig. X`, `Table Y` within 50 pt above/below asset bbox. Set `caption_block_id` on asset.
- **Educational Region Tagging**: Structurally classify TOC, Glossary, Bibliography, Footnotes, Sidebars, Exercises, and Worked Examples based on heading regex and layout positioning.

---

## 13. Phase 1C Implementation Details

### PDF Repair & Sandboxing
- **Repair Flow**:
  1. Catch PyMuPDF `fitz.FileDataError`.
  2. Invoke PyMuPDF repair script: `doc.save(clean=True, deflate=True, garbage=3)`.
  3. If repair succeeds, proceed with processing and attach `REPAIRED_PDF` warning.
  4. If repair fails, reject document with `CORRUPTED` status code.
- **Sandboxing**:
  - Run PDF extraction workers inside Python `subprocess` / `ProcessPoolExecutor` with dropped privileges.
  - Resource limits enforced via `resource` module (Unix):
    - CPU Time Limit: 60 seconds per page.
    - Memory Limit: 1.5 GB RLIMIT_AS per worker process.
    - Render Pixel Limit: Max $4000 \times 4000$ pixels per page render.
    - Stream Decompression Capping: Reject streams decompressing to $>100 \times$ compressed size (zip bomb protection).

### Security & Prompt Injection
- **Hidden Text Detection**:
  - Compare native text layer coordinates with visible page render.
  - Detect text rendered with `render_mode = 3` (invisible text), text rendered white-on-white (font color == background color), or coordinates outside MediaBox.
  - Tag hidden text blocks with `role = "hidden"` and attach `HIDDEN_TEXT_DETECTED` warning.
- **Prompt Injection Defense**:
  - Scan extracted text for instruction override patterns (e.g., `"ignore previous instructions"`, `"system prompt:"`, `"you are now an AI"`).
  - Attach `POSSIBLE_PROMPT_INJECTION` warning code.
  - **Contract with Phase 2**: StructuredDocument text MUST be wrapped in data XML wrappers (`<untrusted_document_content>`) when passed to downstream LLM components.

---

## 14. Engine Adapter Architecture

To prevent tight coupling to specific parsers or OCR libraries, all processing tools are wrapped behind abstract base interfaces.

```python
# Conceptual Engine Adapter Specification
from abc import ABC, abstractmethod
from typing import Dict, Any, List

class BaseEngineAdapter(ABC):
    @property
    @abstractmethod
    def name(self) -> str: pass

    @property
    @abstractmethod
    def version(self) -> str: pass


class TextExtractorAdapter(BaseEngineAdapter):
    @abstractmethod
    def extract_page_text(self, pdf_path: str, page_index: int) -> Dict[str, Any]: pass


class OCREngineAdapter(BaseEngineAdapter):
    @abstractmethod
    def ocr_region(self, image_bytes: bytes, languages: List[str]) -> Dict[str, Any]: pass


class TableEngineAdapter(BaseEngineAdapter):
    @abstractmethod
    def extract_tables(self, pdf_path: str, page_index: int) -> List[Dict[str, Any]]: pass
```

---

## 15. Routing Logic & Escalation Ladder

```
                                  +---------------------------------------+
                                  |       Cheap Page Inspection           |
                                  +-------------------+-------------------+
                                                      |
                                                      v
                                  +---------------------------------------+
                                  |         Routing Decision Engine       |
                                  +-------------------+-------------------+
                                                      |
        +-------------------------+-------------------+-------------------------+
        |                         |                   |                         |
        v                         v                   v                         v
+---------------+         +---------------+   +---------------+         +---------------+
| Rung 1: Native|         | Rung 2: Layout|   | Rung 3: OCR   |         | Rung 4: Pres. |
| Text Extraction|        | Analysis      |   | Pipeline      |         | Asset Fallback|
+---------------+         +---------------+   +---------------+         +---------------+
 (Char Count>100           (Multi-column /     (Scanned Page /           (Failed OCR /
  & Trash Ratio             Tables / Math       Garbled Text              Unparseable
  < 0.15)                   Regions)            Layer)                    Complex Region)
```

### Routing Signals & Thresholds
1. **Character Count ($C$)**: Total native text characters on page.
2. **Garbage Score ($G$)**:
   $$G = \frac{\text{Count of replacement/PUA characters} + \text{Non-printable characters}}{C}$$
3. **Image Coverage ($I$)**: Fraction of total page bounding box covered by raster images.
4. **Vector Density ($V$)**: Count of vector drawing paths on page.

| Page Type Decision | Exact Signal Conditions | Primary Rung |
| :--- | :--- | :--- |
| **`blank`** | Ink density $< 0.001$ AND $C < 10$ AND $V < 5$ | Skip processing (Mark `empty`) |
| **`native`** | $C \ge 100$ AND $G < 0.15$ AND $I < 0.50$ | Rung 1 (PyMuPDF Native) |
| **`scanned`** | $C < 50$ AND $I \ge 0.60$ | Rung 3 (Tesseract OCR) |
| **`hybrid`** | $C \ge 50$ AND $I \ge 0.25$ AND $G < 0.15$ | Rung 1 (Native Text) + Rung 3 (OCR Image Regions) |
| **`garbled`** | $C \ge 50$ AND $G \ge 0.15$ | Rung 3 (Tesseract OCR Override) |

---

## 16. OCR Pipeline Details

```
[ Scanned / Garbled Region ]
             │
             ▼
[ Render Image @ 300 DPI ]
             │
             ▼
[ OpenCV Grayscale Conversion ]
             │
             ▼
[ Radon Deskewing (Rotate if Angle > 0.5°) ]
             │
             ▼
[ Otsu Adaptive Thresholding ]
             │
             ▼
[ Tesseract 5 C++ Execution (-l eng+hin) ]
             │
             ▼
[ Extract Words, BBoxes & Confidences ]
             │
             ▼
    Is Confidence >= 0.60?
    ├── YES ──► Output Text Block (status: ok)
    └── NO  ──► Output Text Block (status: ok_low_confidence, Warning: LOW_OCR_CONFIDENCE)
```

---

## 17. Table Extraction Pipeline Details

```
[ Page Table Region Detected ]
             │
             ▼
Is Vector Grid / Lines Present?
    ├── YES (Native PDF) ──► Invoke pdfplumber / Camelot Lattice Parser
    └── NO  (Scanned)    ──► Apply OpenCV Morphological Line Detection
             │
             ▼
[ Construct Matrix Cells (Row, Col, Rowspan, Colspan) ]
             │
             ▼
[ Extract Text per Cell via Native or OCR ]
             │
             ▼
    Is Table Matrix Reconstructed & Valid?
    ├── YES ──► Output Structured Table JSON (status: ok)
    └── NO  ──► Crop Table BBox as PNG Asset ──► Preserve Asset ──► Attach Warning: TABLE_RECONSTRUCTION_FAILED
```

---

## 18. Mathematics Pipeline Details

```
[ Page Region ] ──► [ Math Signal Scan (Unicode Math / CMEX Fonts / Regex Symbols) ]
                         │
                         ▼
             Math Region Identified?
                         │
        +----------------+----------------+
        │                                 │
        v                                 v
[ Inline Math ]                  [ Display Equation ]
  Preserve span in sentence        Is Equation Image or Native?
  Set is_math = True               ├── Native ──► Extract LaTeX / MathML
                                   └── Image  ──► Run ONNX LaTeX-OCR
                                                      │
                                                      v
                                             Is Confidence >= 0.85?
                                             ├── YES ──► Output LaTeX String
                                             └── NO  ──► Crop Math PNG ──► Attach Warning: MATH_UNPARSED
```

---

## 19. Figure & Chart Pipeline Details

```
[ Image / Vector Region ]
             │
             ▼
Is Image Decorative/Icon? (Size < 50px OR Repeated > 3 Pages)
    ├── YES ──► Set is_decorative = True (Do not pass to vision processing)
    └── NO  ──► Extract / Crop Image Asset (Assign asset_id, compute SHA-256)
             │
             ▼
[ Locate Nearby Text within 50pt (Caption Search) ]
             │
             ▼
  Caption Found ("Figure X...")?
  ├── YES ──► Associate caption_block_id with Asset
  └── NO  ──► Leave caption_block_id = null
             │
             ▼
Is Chart / Graph Type Detected?
    ├── YES ──► Extract Axis Labels, Title, Legend Text ──► Store Chart Metadata
    └── NO  ──► Store Raw Image Asset Reference
```

---

## 20. Educational Structure Tagging Pipeline

Educational structural elements are tagged by layout heuristics and regex matching without applying semantic interpretation:

- **Table of Contents (TOC)**: Text blocks containing dot leaders (`. . . . .`), trailing page numbers, and heading `Contents` / `Table of Contents` $\rightarrow$ `role = "toc"`.
- **Glossary**: Two-column or bold-prefix term definition patterns under `Glossary` heading $\rightarrow$ `role = "glossary"`.
- **Bibliography / References**: Square bracket citations (`[1]`, `[2]`) or author-year patterns under `References` heading $\rightarrow$ `role = "bibliography"`.
- **Footnotes**: Bottom page margin band blocks starting with superscript digits or symbols (`*`, `1`) $\rightarrow$ `role = "footnote"`.
- **Sidebars / Callouts**: Bounded text boxes with background shading or distinct side borders $\rightarrow$ `role = "sidebar"`.
- **Worked Examples / Exercises**: Blocks prefixed with `Example X.Y`, `Exercise Z`, `Problem N` $\rightarrow$ `role = "worked_example"` / `role = "exercise"`.

---

## 21. Security Architecture

1. **Sandboxed Worker Process**: Parsers execute in subprocesses with restricted filesystem permissions (read-only access to source PDF, write access only to assigned execution directory).
2. **Resource Capping**:
   - `max_file_size_bytes`: 100 MB.
   - `max_page_count`: 500 pages.
   - `max_page_render_pixels`: $4000 \times 4000$ pixels.
   - `max_decompressed_stream_bytes`: 50 MB per stream.
   - `per_page_timeout_seconds`: 60 seconds.
3. **Execution Block**: PDF JavaScript actions (`/JS`, `/JavaScript`), Launch actions (`/Launch`), and embedded executables (`/EmbeddedFiles`) are explicitly disabled during PyMuPDF parsing.

---

## 22. Job & State Architecture

### Document Job State Transition Table

```
 [Upload] ──► QUEUED ──► VALIDATING ──► ANALYZING ──► EXTRACTING ──► AGGREGATING ──► COMPLETED
                 │           │              │             │               │
                 └───────────┴──────────────┴─────────────┴───────────────┴─────► FAILED
                                                                                (or COMPLETED_WITH_WARNINGS)
```

| State | Trigger / Description | Valid Next States |
| :--- | :--- | :--- |
| `queued` | Upload received, job recorded in SQLite | `validating`, `cancelled` |
| `validating` | PDF integrity, magic bytes, and encryption check | `analyzing`, `failed` |
| `analyzing` | Cheap Page Inspection & Routing across all pages | `extracting`, `failed` |
| `extracting` | Pass A: Streaming per-page parallel extraction | `aggregating`, `failed`, `cancelled` |
| `aggregating` | Pass B: Document-level pass (headers, outline, links) | `completed`, `completed_with_warnings`, `failed` |
| `completed` | Pipeline completed successfully with zero severe warnings | None (Terminal) |
| `completed_with_warnings` | Pipeline completed with non-fatal page/block warnings | None (Terminal) |
| `failed` | Fatal error encountered (corrupt PDF, system error) | `queued` (Reprocess) |
| `cancelled` | User or timeout cancelled processing | None (Terminal) |

---

## 23. Storage Architecture

```
storage/
└── documents/
    └── {document_id}/                  # SHA-256 derived document UUID
        ├── original/
        │   └── source.pdf              # Immutable uploaded original file
        ├── pages/
        │   ├── page_0000.png           # 150 DPI render preview image
        │   └── page_0001.png
        ├── assets/
        │   ├── fig_0001_p00_a1b2.png   # Preserved figure asset
        │   └── tbl_0001_p02_c3d4.png   # Preserved table crop asset
        ├── intermediate/
        │   ├── page_0000_raw.json      # Pass A per-page extraction output
        │   └── page_0001_raw.json
        ├── structured/
        │   └── document.json           # Final StructuredDocument JSON
        └── logs/
            └── execution.log           # Structured JSON processing logs
```

---

## 24. Caching & Idempotency Architecture

Cache key generated via SHA-256 digest:
$$\text{CacheKey} = \text{SHA256}(\text{FileContent} + \text{PipelineVersion} + \text{ConfigurationJSON})$$

1. Upon upload, compute `CacheKey`.
2. Check SQLite `documents` table for existing record matching `CacheKey` with status `completed` or `completed_with_warnings`.
3. If match found: copy cached `StructuredDocument` to new request ID and return immediately (instant response).
4. Page-Level Invalidation: Stage/page reprocessing allows targeting individual pages (e.g., re-running page 5 with modified OCR settings) without invalidating cached results for pages 1–4.

---

## 25. Canonical StructuredDocument JSON Schema

```json
{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "title": "StructuredDocument",
  "type": "object",
  "required": [
    "schema_version",
    "pipeline_version",
    "document_id",
    "source",
    "metadata",
    "outline",
    "pages",
    "assets",
    "links",
    "annotations",
    "warnings"
  ],
  "properties": {
    "schema_version": { "type": "string", "enum": ["1.0.0"] },
    "pipeline_version": { "type": "string" },
    "document_id": { "type": "string" },
    "source": {
      "type": "object",
      "required": ["sha256", "filename", "size_bytes"],
      "properties": {
        "sha256": { "type": "string" },
        "filename": { "type": "string" },
        "size_bytes": { "type": "integer" }
      }
    },
    "metadata": {
      "type": "object",
      "required": ["page_count", "title", "processing_status"],
      "properties": {
        "page_count": { "type": "integer" },
        "title": {
          "type": "object",
          "properties": {
            "value": { "type": "string" },
            "source": { "type": "string", "enum": ["pdf_metadata", "inferred", "user"] }
          }
        },
        "processing_status": {
          "type": "string",
          "enum": ["completed", "completed_with_warnings", "failed"]
        }
      }
    },
    "outline": {
      "type": "array",
      "items": {
        "type": "object",
        "required": ["section_id", "title", "level", "page_start"],
        "properties": {
          "section_id": { "type": "string" },
          "title": { "type": "string" },
          "level": { "type": "integer" },
          "page_start": { "type": "integer" },
          "children": { "type": "array" }
        }
      }
    },
    "pages": {
      "type": "array",
      "items": {
        "type": "object",
        "required": [
          "page_index",
          "page_label",
          "width",
          "height",
          "orientation",
          "rotation_applied",
          "page_type",
          "status",
          "blocks"
        ],
        "properties": {
          "page_index": { "type": "integer" },
          "page_label": { "type": "string" },
          "width": { "type": "number" },
          "height": { "type": "number" },
          "orientation": { "type": "string", "enum": ["portrait", "landscape"] },
          "rotation_applied": { "type": "integer", "enum": [0, 90, 180, 270] },
          "page_type": { "type": "string", "enum": ["native", "scanned", "hybrid", "blank", "near_blank"] },
          "status": { "type": "string", "enum": ["pending", "ok", "ok_low_confidence", "empty", "failed", "skipped"] },
          "blocks": {
            "type": "array",
            "items": {
              "type": "object",
              "required": [
                "block_id",
                "type",
                "role",
                "bbox",
                "content",
                "language",
                "reading_order",
                "extraction_method",
                "confidence",
                "status"
              ],
              "properties": {
                "block_id": { "type": "string" },
                "type": {
                  "type": "string",
                  "enum": [
                    "heading", "paragraph", "list_item", "table", "equation",
                    "figure", "caption", "footnote", "code", "sidebar",
                    "header", "footer", "page_number", "watermark",
                    "toc_entry", "index_entry", "other", "unknown"
                  ]
                },
                "role": { "type": "string" },
                "bbox": {
                  "type": "array",
                  "items": { "type": "number" },
                  "minItems": 4,
                  "maxItems": 4
                },
                "content": {
                  "type": "object",
                  "required": ["text", "text_raw"],
                  "properties": {
                    "text": { "type": "string" },
                    "text_raw": { "type": "string" },
                    "structured_data": { "type": "object" }
                  }
                },
                "language": { "type": "string" },
                "reading_order": { "type": "integer" },
                "section_id": { "type": ["string", "null"] },
                "extraction_method": { "type": "string", "enum": ["native", "ocr", "table_parser", "math_parser", "preserved"] },
                "engine": {
                  "type": "object",
                  "properties": {
                    "name": { "type": "string" },
                    "version": { "type": "string" }
                  }
                },
                "confidence": { "type": "number", "minimum": 0.0, "maximum": 1.0 },
                "status": { "type": "string", "enum": ["ok", "ok_low_confidence", "preserved_only", "unsupported", "failed", "empty"] },
                "continues_from": { "type": ["string", "null"] },
                "continues_to": { "type": ["string", "null"] },
                "asset_ids": { "type": "array", "items": { "type": "string" } },
                "warnings": { "type": "array", "items": { "type": "string" } }
              }
            }
          }
        }
      }
    },
    "assets": {
      "type": "array",
      "items": {
        "type": "object",
        "required": ["asset_id", "type", "page_index", "bbox", "uri", "sha256", "is_decorative"],
        "properties": {
          "asset_id": { "type": "string" },
          "type": { "type": "string", "enum": ["figure", "table_crop", "equation_crop", "watermark"] },
          "page_index": { "type": "integer" },
          "bbox": { "type": "array", "items": { "type": "number" } },
          "uri": { "type": "string" },
          "sha256": { "type": "string" },
          "caption_block_id": { "type": ["string", "null"] },
          "is_decorative": { "type": "boolean" }
        }
      }
    },
    "links": { "type": "array" },
    "annotations": { "type": "array" },
    "warnings": {
      "type": "array",
      "items": {
        "type": "object",
        "required": ["code", "severity", "message"],
        "properties": {
          "code": {
            "type": "string",
            "enum": [
              "LOW_OCR_CONFIDENCE", "GARBLED_TEXT_LAYER", "UNSUPPORTED_LANGUAGE",
              "TABLE_RECONSTRUCTION_FAILED", "TABLE_LOW_CONFIDENCE", "MATH_UNPARSED",
              "PAGE_FAILED", "PAGE_TIMEOUT", "HIDDEN_TEXT_DETECTED",
              "POSSIBLE_PROMPT_INJECTION", "HEADING_HIERARCHY_CONFLICT",
              "ROTATION_CORRECTED", "DUPLICATE_PAGE_CANDIDATE", "REPAIRED_PDF",
              "RESOURCE_LIMIT_HIT", "ENGINE_FALLBACK_USED", "OWNER_PASSWORD_RESTRICTED"
            ]
          },
          "severity": { "type": "string", "enum": ["info", "low", "medium", "high", "critical"] },
          "page_index": { "type": ["integer", "null"] },
          "block_id": { "type": ["string", "null"] },
          "message": { "type": "string" }
        }
      }
    }
  }
}
```

---

## 26. API Specification

### `POST /documents`
- **Description**: Upload a PDF document for Phase 1 ingestion.
- **Content-Type**: `multipart/form-data`
- **Request Body**:
  - `file`: PDF binary stream.
  - `options` (optional JSON string): Configuration overrides (e.g., target OCR languages).
- **Response `202 Accepted`**:
```json
{
  "document_id": "doc_9a8b7c6d5e4f",
  "status": "queued",
  "created_at": "2026-09-24T18:00:00Z",
  "estimated_duration_seconds": 12.5
}
```

### `GET /documents/{id}`
- **Description**: Fetch high-level document metadata and processing status.
- **Response `200 OK`**:
```json
{
  "document_id": "doc_9a8b7c6d5e4f",
  "status": "completed_with_warnings",
  "page_count": 42,
  "progress_percentage": 100.0,
  "warnings_count": 3
}
```

### `GET /documents/{id}/status`
- **Description**: Lightweight endpoint for polling extraction progress.
- **Response `200 OK`**:
```json
{
  "document_id": "doc_9a8b7c6d5e4f",
  "status": "extracting",
  "processed_pages": 18,
  "total_pages": 42,
  "current_stage": "Pass A Page 19"
}
```

### `GET /documents/{id}/structured`
- **Description**: Fetch the complete canonical `StructuredDocument` JSON.
- **Response `200 OK`**: `StructuredDocument` JSON schema payload.

### `GET /documents/{id}/pages/{page}`
- **Description**: Fetch extracted structured data for a single specific page.
- **Response `200 OK`**: Page object payload.

### `GET /documents/{id}/assets/{asset}`
- **Description**: Download extracted binary image asset (PNG).
- **Response `200 OK`**: Image file stream (`image/png`).

### `POST /documents/{id}/reprocess`
- **Description**: Trigger stage-level or page-level reprocessing.
- **Request Body**:
```json
{
  "target_pages": [5, 6],
  "force_ocr": true
}
```
- **Response `202 Accepted`**: Reprocessing job status.

### `POST /documents/{id}/cancel`
- **Description**: Cancel an active processing job.
- **Response `200 OK`**: `{ "status": "cancelled" }`.

---

## 27. Repository Directory Structure

```
taproot/
├── backend/                        # API Web Application Layer
│   ├── app.py                      # FastAPI instance entrypoint
│   ├── config.py                   # Configuration & Environment Settings
│   ├── routes/                     # API Endpoint Definitions
│   │   ├── documents.py
│   │   └── verification.py
│   └── dependencies.py             # Dependency Injection
├── ingestion/                      # Ingestion Core Library
│   ├── pipeline.py                 # Pipeline Coordinator
│   ├── validator.py                # PDF Validation & Repair
│   ├── inspector.py                # Cheap Page Inspection
│   ├── router.py                   # Escalation Router
│   ├── coordinate.py               # Coordinate Normalization
│   └── pass_b.py                   # Pass B Aggregator
├── adapters/                       # Abstract Engine Adapters
│   ├── base.py                     # Base Interfaces
│   ├── pymupdf_adapter.py          # PyMuPDF Native Adapter
│   ├── tesseract_adapter.py        # Tesseract OCR Adapter
│   ├── pdfplumber_adapter.py       # Table Extraction Adapter
│   └── latex_ocr_adapter.py        # Math Extraction Adapter
├── extraction/                     # Specialized Feature Parsers
│   ├── text.py                     # Native Text Extractor
│   ├── ocr.py                      # OCR Processing Engine
│   ├── layout.py                   # Reading Order & Column Detector
│   ├── tables.py                   # Table Reconstruction Engine
│   ├── math.py                     # Math Detection & Parsing
│   ├── figures.py                  # Figure & Vector Cluster Extractor
│   └── structure.py                # Section Hierarchy & Tagging Engine
├── security/                       # Security & Sandboxing Layer
│   ├── sandbox.py                  # Process Isolation & Limits
│   └── prompt_injection.py         # Prompt Injection & Hidden Text Detector
├── storage/                        # Persistence Layer
│   ├── store.py                    # Filesystem Asset Store
│   └── db.py                       # SQLite State Database
├── schemas/                        # Pydantic & JSON Schemas
│   └── document.py                 # Canonical StructuredDocument Schema
├── evaluation/                     # Evaluation & Metrics
│   ├── runner.py                   # Evaluation Harness Runner
│   ├── metrics.py                  # CER, WER, Rank Correlation Implementations
│   └── golden_set/                 # 27 Evaluation Test Files
├── tests/                          # Automated Test Suite
│   ├── unit/                       # Unit Tests
│   ├── integration/                # Integration Tests
│   ├── failure/                    # Failure Mode Tests
│   └── security/                   # Security Vulnerability Tests
├── web/                            # Verification UI
│   └── index.html                  # Lightweight HTML/JS Verification Interface
├── configs/                        # Configuration Files
│   └── default.yaml                # Standard Execution Config
├── requirements.txt                # Python Dependencies
└── AGENTS.md                       # Repository Agent Instructions
```

---

## 28. System Configuration

```yaml
# configs/default.yaml
pipeline:
  version: "2026.09.0"
  schema_version: "1.0.0"

limits:
  max_file_size_bytes: 104857600   # 100 MB
  max_page_count: 500
  per_page_timeout_seconds: 60
  max_worker_memory_mb: 1500
  max_render_pixels: 16000000      # 4000x4000

inspection:
  blank_ink_ratio_threshold: 0.001
  scanned_image_coverage_threshold: 0.60
  garbled_text_ratio_threshold: 0.15

ocr:
  engine: "tesseract"
  dpi: 300
  default_languages: ["eng", "hin"]
  confidence_threshold: 0.60

tables:
  native_engine: "pdfplumber"
  min_confidence: 0.70

math:
  enable_cpu_latex_ocr: true
  confidence_threshold: 0.85

storage:
  root_dir: "storage/documents"
  retention_days: 30
```

---

## 29. Error Handling Hierarchy & Fallbacks

```
Phase1BaseException
├── ValidationError (Invalid format, corrupt file, encrypted)
├── ResourceLimitError (File size > 100MB, Page count > 500)
├── PageProcessingError (Failure isolated to single page)
│   ├── RenderError
│   ├── OCRError
│   ├── TableError
│   └── MathError
├── SecurityError (Malicious stream, extreme decompression ratio)
└── StorageError (Disk full, read/write permission failure)
```

### Error Recovery Rules
1. **Fatal Errors**: `ValidationError` on unrepairable PDF $\rightarrow$ Abort job, set status to `failed`.
2. **Non-Fatal Page Errors**: `PageProcessingError` during Pass A $\rightarrow$ Catch exception, mark page status as `failed`, generate `PAGE_FAILED` warning, and continue to next page.
3. **Engine Fallback**: If Table Parser fails $\rightarrow$ Fallback to cropping table image asset, set status `preserved_only`, attach `TABLE_RECONSTRUCTION_FAILED` warning, and complete document as `completed_with_warnings`.

---

## 30. Complete Testing Strategy

### 1. Unit Tests
- `test_validation.py`: Validate magic byte checks, file size capping, repair triggers.
- `test_coordinate_normalization.py`: Verify conversion of MediaBox, CropBox, and `/Rotate` values (90°, 180°, 270°) to top-left points canonical space.
- `test_text_normalization.py`: Check NFC Unicode normalization, ligature replacement, and hyphenation rejoining.
- `test_reading_order.py`: Test single-column, two-column, and sidebar reading order sorting.

### 2. Integration Tests
- Run complete PDFs through the pipeline and validate `StructuredDocument` output against JSON Schema.
- TestPass A parallel execution and Pass B outline generation.

### 3. Failure & Security Tests
- Ingest truncated/corrupted PDFs and verify automatic repair execution.
- Ingest password-protected PDFs and verify `ENCRYPTED` reject status.
- Ingest PDFs with hidden white-on-white text and verify `HIDDEN_TEXT_DETECTED` warning generation.
- Test process memory limit enforcement using synthetic large-render streams.

---

## 31. Golden Dataset (27 Benchmark Files)

A dedicated evaluation dataset containing 27 representative files covering all target PDF conditions:

1. `01_clean_digital_textbook.pdf`: Standard single-column digital textbook.
2. `02_single_column_notes.pdf`: Handwritten/typed student lecture notes.
3. `03_two_column_textbook.pdf`: Multi-column engineering textbook page.
4. `04_multipage_lecture_notes.pdf`: 50-page lecture slide/notes compilation.
5. `05_fully_scanned_handout.pdf`: Pure image-based scanned document.
6. `06_mixed_native_scanned.pdf`: Alternate native text and scanned pages.
7. `07_hindi_english_mixed.pdf`: Bilingual Hindi + English study guide.
8. `08_table_heavy_data.pdf`: Financial/scientific tables with merged cells.
9. `09_equation_heavy_physics.pdf`: Differential equations and physics formulas.
10. `10_diagram_heavy_biology.pdf`: High-density vector diagrams with captions.
11. `11_chart_heavy_statistics.pdf`: Bar charts, line graphs, and scatter plots.
12. `12_headers_footers_repeated.pdf`: Running headers, footers, and page numbers.
13. `13_watermarked_draft.pdf`: Heavy diagonal "DRAFT" watermark text.
14. `14_annotated_student_pdf.pdf`: PDF with user highlights, sticky notes, and comments.
15. `15_with_toc_and_bookmarks.pdf`: Valid PDF outline bookmarks and printed TOC page.
16. `16_with_glossary.pdf`: Technical terminology glossary list.
17. `17_with_index.pdf`: End-of-book alphabetical index.
18. `18_with_exercises.pdf`: End-of-chapter practice questions.
19. `19_question_paper_mcq.pdf`: Multiple-choice exam paper with options.
20. `20_slide_deck.pdf`: 16:9 landscape lecture slides presentation.
21. `21_rotated_pages_90_270.pdf`: Mixed portrait and rotated landscape pages.
22. `22_blank_and_near_blank.pdf`: Includes intentional blank filler pages.
23. `23_corrupt_repairable_xref.pdf`: Truncated xref table (repair test).
24. `24_encrypted_owner_password.pdf`: Restricted-copy encrypted PDF.
25. `25_large_100_page_doc.pdf`: 100-page comprehensive document.
26. `26_hidden_text_injection.pdf`: White-on-white prompt injection attempt.
27. `27_resource_heavy_image.pdf`: Extreme 8K image embedded in single page.

---

## 32. Evaluation Metrics

| Metric Name | Capability Tested | Mathematical Formulation / Target Logic |
| :--- | :--- | :--- |
| **Character Error Rate (CER)** | Native & OCR Text | $\text{CER} = \frac{S + D + I}{N}$ ($S$=substitutions, $D$=deletions, $I$=insertions, $N$=ground truth length) |
| **Word Error Rate (WER)** | Text Quality | $\text{WER} = \frac{S_w + D_w + I_w}{N_w}$ measured on normalized words |
| **Reading Order Edit Distance** | Reading Order | Levenshtein distance on block ID sequence compared to human ground truth |
| **Heading Precision / Recall / F1** | Structure Detection | $F_1 = 2 \cdot \frac{\text{Precision} \cdot \text{Recall}}{\text{Precision} + \text{Recall}}$ on heading block identification |
| **Header/Footer F1** | Repeated Content | Precision and Recall on tagging headers, footers, and page numbers |
| **Table Structure Similarity** | Table Extraction | Tree Edit Distance Score (TEDS) on reconstructed HTML/matrix vs ground truth |
| **Bounding Box IoU** | Region Detection | $\text{IoU} = \frac{\text{Area}(\text{BBox}_{pred} \cap \text{BBox}_{gt})}{\text{Area}(\text{BBox}_{pred} \cup \text{BBox}_{gt})}$ |

---

## 33. Acceptance Thresholds

| Capability Area | Baseline Target (Minimum Pass) | Good Target | Stretch Target |
| :--- | :--- | :--- | :--- |
| **Native Text CER** | $< 2.0\%$ | $< 0.5\%$ | $< 0.1\%$ |
| **Scanned OCR CER (English)** | $< 10.0\%$ | $< 5.0\%$ | $< 2.0\%$ |
| **Scanned OCR CER (Hindi)** | $< 15.0\%$ | $< 8.0\%$ | $< 4.0\%$ |
| **Reading Order Rank Correlation** | $> 0.85$ | $> 0.95$ | $> 0.98$ |
| **Heading Detection F1** | $> 0.80$ | $> 0.90$ | $> 0.95$ |
| **Header/Footer Removal F1** | $> 0.85$ | $> 0.92$ | $> 0.98$ |
| **Table TEDS Score** | $> 0.70$ | $> 0.82$ | $> 0.90$ |
| **Document Reliability** | $> 95\%$ Docs Processed | $> 99\%$ Docs Processed | $100\%$ Docs Processed |

---

## 34. CPU Performance & Resource Plan

### Performance Strategy for CPU Laptops
- **Page Streaming**: Process pages sequentially or in a small worker pool (`max_workers = min(4, cpu_count)`). Never load full PDF document tree into memory.
- **Image Downsampling**: Render inspection previews at 150 DPI; invoke 300 DPI high-resolution rendering only on targeted OCR regions.
- **Temporary Memory Cleanup**: Explicitly call `gc.collect()` and clear PyMuPDF page pixmaps after writing intermediate JSON.

### Performance Target Benchmarks (8 GB RAM CPU Laptop)

| Document Type / Length | Expected Processing Time | Peak RAM Limit |
| :--- | :--- | :--- |
| **1-Page Native PDF** | $< 0.5$ seconds | $< 100$ MB |
| **10-Page Native PDF** | $< 2.5$ seconds | $< 150$ MB |
| **10-Page Scanned PDF (OCR)** | $< 15.0$ seconds | $< 350$ MB |
| **50-Page Native Textbook** | $< 10.0$ seconds | $< 250$ MB |
| **100-Page Mixed PDF** | $< 45.0$ seconds | $< 400$ MB |
| **500-Page Large Document** | $< 3.5$ minutes | $< 500$ MB |

---

## 35. Google Colab Policy

Google Colab is strictly **OPTIONAL** and intended solely for benchmarking, offline experimentation, and dataset creation.

| Component / Task | Run Locally on CPU? | Colab Optional? | Selection Status |
| :--- | :--- | :--- | :--- |
| **FastAPI Backend & Pipeline** | **YES (Mandatory)** | NO | LOCAL CPU |
| **PyMuPDF Native Extraction** | **YES (Mandatory)** | NO | LOCAL CPU |
| **Tesseract OCR (Eng + Hin)** | **YES (Mandatory)** | NO | LOCAL CPU |
| **Table Extraction (`pdfplumber`)** | **YES (Mandatory)** | NO | LOCAL CPU |
| **Quantized ONNX Math LaTeX-OCR** | **YES (Supported)** | YES (For heavy benchmark) | LOCAL CPU |
| **Heavy Vision Layout Models** | NO | YES (For model evaluation) | COLAB OPTIONAL |

---

## 36. Step-by-Step Implementation Sequence

```
[Step 01: Skeleton] ──► [Step 02: Storage & DB] ──► [Step 03: Validation] ──► [Step 04: Inspection]
                                                                                      │
[Step 08: Schema]   ◄── [Step 07: Layout]      ◄── [Step 06: Coord Norm]  ◄── [Step 05: Native Text]
        │
        ▼
[Step 09: Pass B]   ──► [Step 10: Section Tree] ──► [Step 11: OCR Adapter] ──► [Step 12: Tables]
                                                                                      │
[Step 16: Links]    ◄── [Step 15: Edu Tagging]  ◄── [Step 14: Figures]     ◄── [Step 13: Math]
        │
        ▼
[Step 17: Security] ──► [Step 18: Caching]    ──► [Step 19: API Layer]   ──► [Step 20: Golden Set]
                                                                                      │
[Phase 1 Complete]  ◄── [Step 23: 1C Verify]   ◄── [Step 22: 1B Verify]   ◄── [Step 21: 1A Verify]
```

1. **Step 1 — Project Skeleton**: Initialize repository structure, virtual environment, and dependency configuration (`requirements.txt`).
2. **Step 2 — Storage & Database**: Implement SHA-256 filesystem store and SQLite job state tracker.
3. **Step 3 — PDF Validation**: Implement validation and PyMuPDF automatic repair logic.
4. **Step 4 — Cheap Page Inspection**: Build preview renderer and metrics inspector (ink ratio, character count, image coverage).
5. **Step 5 — Native Text Extraction**: Implement PyMuPDF word/span extraction with Unicode normalization and hyphenation repair.
6. **Step 6 — Coordinate Normalization**: Implement coordinate transform engine to top-left points canonical space.
7. **Step 7 — Layout & Reading Order**: Build multi-column layout detector and reading order sorter.
8. **Step 8 — Page-Level Schema**: Implement Pydantic schema for Pass A intermediate JSON.
9. **Step 9 — Pass B Aggregator**: Implement multi-page repeated header/footer and page number classifier.
10. **Step 10 — Section Hierarchy**: Build document section tree builder combining font statistics and PDF bookmarks.
11. **Step 11 — OCR Engine Adapter**: Implement Tesseract 5 adapter with English and Hindi language support.
12. **Step 12 — Table Extraction**: Implement `pdfplumber`/`Camelot` lattice parser with image crop fallback.
13. **Step 13 — Math Processing**: Implement math symbol scanner and ONNX LaTeX-OCR adapter.
14. **Step 14 — Figures & Vectors**: Implement raster image extraction and OpenCV vector path clustering.
15. **Step 15 — Educational Tagging**: Implement layout/regex tagging for TOC, Glossary, Bibliography, and Exercises.
16. **Step 16 — PDF Links & Annotations**: Preserve PDF outlines, internal links, external URLs, and user highlights/comments.
17. **Step 17 — Security & Sandboxing**: Implement process resource limits, hidden text detector, and prompt injection scanner.
18. **Step 18 — Caching & Idempotency**: Implement SHA-256 exact match caching and stage-level reprocessing.
19. **Step 19 — FastAPI Endpoints**: Build complete REST API specification and verification endpoints.
20. **Step 20 — Golden Dataset Setup**: Populate `evaluation/golden_set/` with 27 benchmark PDFs.
21. **Step 21 — Phase 1A Verification**: Verify DoD for Phase 1A baseline digital PDFs.
22. **Step 22 — Phase 1B Verification**: Verify DoD for Phase 1B complex educational PDFs.
23. **Step 23 — Phase 1C Verification**: Verify DoD for Phase 1C robustness and security.

---

## 37. Phase-by-Phase Definition of Done

### Definition of Done — Phase 1A
1. 100% of valid test digital PDFs produce valid `StructuredDocument` JSON matching schema.
2. Reading order is verified correct on single-column and two-column layouts.
3. Physical `page_index` and printed `page_label` are preserved independently.
4. Headings, paragraphs, and lists are structurally distinguishable in output.
5. Repeated headers, footers, and page numbers are tagged with appropriate roles without polluting main text.
6. Section tree outline is generated for every document.

### Definition of Done — Phase 1B
1. Scanned educational PDFs route successfully to Tesseract OCR.
2. Mixed English + Hindi scanned pages produce block-level language metadata.
3. Tables retain matrix structure or are preserved as image assets with `TABLE_RECONSTRUCTION_FAILED` warnings.
4. Equations are isolated into `equation` blocks or spans without corrupting prose.
5. Raster and vector figures are extracted, stored as assets, and associated with nearby captions.
6. Educational structures (TOC, Glossary, Bibliography) are structurally tagged.

### Definition of Done — Phase 1C
1. Corrupt xref PDFs are automatically repaired or gracefully rejected with `CORRUPTED` status.
2. Single page failure does not halt processing of remaining document pages (`completed_with_warnings`).
3. Resource limits prevent process memory usage from exceeding 1.5 GB.
4. Identical document uploads return instant cached results.
5. Hidden text and prompt-injection instructions generate structured security warnings.

---

## 38. Deferred Features

The following features are explicitly deferred beyond Phase 1 and will NOT be implemented in this phase:

- **Right-to-Left (RTL) Optimization**: Hebrew/Arabic specific reading order re-sorting.
- **Vertical Text Support**: Japanese/Chinese vertical text flow analysis.
- **Handwriting Recognition**: Unstructured handwritten notes OCR.
- **Handwritten Mathematics**: Handwriting-to-LaTeX parsing.
- **Heavy Image Dewarping**: 3D mesh surface dewarping for photographed book pages.
- **Bleed-Through Removal**: Advanced image filtering for reverse-page ink bleed.
- **Full Multimedia Understanding**: Embedded audio/video transcription or reasoning.
- **Advanced PDF Portfolios**: Automatic extraction and merging of nested PDF portfolios.
- **Semantic Duplicate Removal**: Cross-document duplicate concept detection.
- **Deep Visual Chart Reasoning**: High-level semantic interpretation of chart trends beyond structural label extraction.

---

## 39. Final End-to-End Architecture & Phase 2 Boundary

```
                     +---------------------------------------+
                     |           PDF Document Upload         |
                     +-------------------+-------------------+
                                         |
                                         v
                     +---------------------------------------+
                     |    Immutable Storage + SHA-256 Hash   |
                     +-------------------+-------------------+
                                         |
                                         v
                     +---------------------------------------+
                     |      Validation & Repair Subsystem    |
                     +-------------------+-------------------+
                                         |
                                         v
                     +---------------------------------------+
                     |     Pass A: Streaming Page Engine     |
                     |   Inspection -> Routing -> Escalation |
                     +-------------------+-------------------+
                                         |
            +----------------------------+----------------------------+
            |                            |                            |
            v                            v                            v
  +------------------+         +------------------+         +------------------+
  |  Native Text     |         |  Tesseract OCR   |         |  Table / Math    |
  |  Extractor       |         |  (Eng + Hin)     |         |  Parsers         |
  +------------------+         +------------------+         +------------------+
            |                            |                            |
            +----------------------------+----------------------------+
                                         |
                                         v
                     +---------------------------------------+
                     |      Pass B: Document Aggregator      |
                     | Headers, Outline Tree, Security Check |
                     +-------------------+-------------------+
                                         |
                                         v
                     +---------------------------------------+
                     |   Canonical StructuredDocument Output |
                     +-------------------+-------------------+
                                         |
=========================================|=========================================
PHASE 1 / PHASE 2 BOUNDARY              |
=========================================|=========================================
                                         v
                     +---------------------------------------+
                     |     Phase 2: Educational AI System    |
                     |  Concept Graphs, NLP, Question Gen    |
                     +---------------------------------------+
```

---

## 40. Risks and Mitigations

| Risk / Failure Mode | Likelihood | Impact | Proposed Mitigation Strategy |
| :--- | :--- | :--- | :--- |
| **1. Memory Exhaustion on 500-page PDF** | Medium | High | Enforce page-by-page streaming processing. Explicit garbage collection (`gc.collect()`) after each page. |
| **2. Poor OCR Accuracy on Low-Quality Scans** | High | Medium | Apply OpenCV preprocessing (grayscale, radon deskew, Otsu thresholding). Flag low-confidence output with `LOW_OCR_CONFIDENCE` warning. |
| **3. Mismatched Bounding Boxes Across Engines** | High | High | Standardize all engine outputs to top-left points canonical space immediately within adapter layer. |
| **4. Long Processing Time on Weak CPUs** | Medium | Medium | Implement cheap inspection routing to skip OCR for digital native pages. Use multi-process page execution. |
| **5. Prompt Injection Attacks in Uploaded Notes** | Low | High | Treat document content strictly as data. Flag instruction patterns with `POSSIBLE_PROMPT_INJECTION` and wrap text in XML tags for Phase 2. |

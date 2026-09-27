# LearnSense / TAPROOT - Recent Changes & Enhancements

## 1. Dynamic LLM Question & Distractor Engine (No Templates / Hardcoding)
- **Eliminated `.cache/llm_replay` Mock Cache Interception**:
  - Removed outdated replay cache that was serving generic fill-in-the-blank mock options (`"Core principle of topic"`, `"Unrelated concept definition"`).
  - Configured `Phase3LLMAdapter` to always execute live LLM calls when `GROQ_API_KEY` is present.
  - Replaced custom User-Agent headers with standard browser headers to prevent Cloudflare/CDN blocks.
- **Dynamic Domain Question Generation (`backend/services/learning_service.py`)**:
  - Concept questions, technical correct answers, and domain-grounded distractor choices are generated live using Groq LLM.
  - Smart option parsing seamlessly handles pure option arrays or letter-prefixed format (`A`, `B`, `C`, `D`).
- **Resilient Burst Handling**:
  - Added automatic retry with backoff and dual-model fallback (`openai/gpt-oss-120b` ↔ `openai/gpt-oss-20b`) in `llm_adapter.py` to seamlessly handle 429 rate limit spikes.

---

## 2. Multi-Format Course Material Upload (Phase 1 & Phase 5)
- **Supported Formats**:
  - **PDF (`.pdf`)**: PyMuPDF extraction, multi-column reading, table-of-contents detection.
  - **PowerPoint (`.pptx`)**: Slide-by-slide text frame extraction, lecture notes, and outline hierarchy via `python-pptx`.
  - **Word Documents (`.docx`)**: Heading/chapter extraction and body paragraph processing via `python-docx`.
  - **Diagrams & Visual Media (`.png`, `.jpg`, `.jpeg`)**: Image verification, metadata extraction, and in-memory conversion to visual document assets via `Pillow` and `PyMuPDF`.
- **Large Document Support**:
  - Increased `MAX_PAGE_COUNT` in `phase5_config.py` from 500 to **3,000 pages**, enabling full college textbooks (1,000+ pages) to be ingested without rejection.
- **Automated Curriculum Synthesis (`backend/services/source_service.py`)**:
  - On upload, text snippets are analyzed by Groq LLM to automatically synthesize formal Subject Title, 8–14 foundational concepts, educational definitions, and prerequisite dependency graphs.
  - Automatically saves `structured_document.json` and initializes `LearningContext` so any uploaded document becomes an interactive subject.

---

## 3. Comprehensive Pedagogical Learning Content & Study Guides
- **Dedicated Learning Lessons Beside Practice Quizzes (`backend/services/learning_service.py`)**:
  - Added `get_concept_learning_content(subject_id, concept_id)` endpoint (`GET /api/subjects/{subject_id}/concepts/{concept_id}/content`).
  - Generates a full university-grade study module for each concept:
    1. **Core Theory & Conceptual Foundation**: Detailed conceptual explanation.
    2. **Intuitive Mental Model & The "Why"**: Real-world analogy and visual mental model.
    3. **Core Principles & Mathematical Rules**: Numbered governing equations, invariants, and properties.
    4. **Step-by-Step Worked Example**: Solved problem with problem statement, sequential steps, and verified solution.
    5. **Common Pitfalls & Misconceptions**: Warning callouts on common student traps.
    6. **Key Takeaway & Rule of Thumb**: High-impact formula or principle banner.
- **Frontend Study Session Workspace (`LearningSession.tsx`)**:
  - Dedicated tabs: **`[BookOpen] Learning Content & Study Guide`** and **`[GraduationCap] Practice Questions & Adaptive Quiz`**.
  - Clicking **"Learn"** on any node opens the in-depth Study Guide directly, with an integrated button to switch to the quiz when ready.

---

## 4. UI/UX Improvements & Workflow Enhancements
- **Onboarding Workflow (`OnboardingWorkflow.tsx`)**:
  - Multi-format file uploader as hero action in Step 1.
  - Diagnostic quiz rendered with clean options and zero penalization for "I don't know" answers.
- **Top Navigation (`TopNavbar.tsx`)**:
  - Direct subject switcher with `+ Upload Material...` and `+ New Subject` actions.
- **Learning Atlas (`LearningAtlas.tsx`, `XRayInspector.tsx`, `CustomConceptNode.tsx`)**:
  - Dynamic topic territory generation for custom subjects (Foundations, Core Principles, Advanced Topics).
  - TypeScript strict-mode null-safety improvements.

# TAPROOT — Adaptive Learning Platform

TAPROOT is a local-first, CPU-friendly AI adaptive learning platform that transforms educational documents (textbooks, PDFs, notes) into structured knowledge graphs, tracks learner mastery using Bayesian Knowledge Tracing (BKT), diagnoses knowledge gaps, generates personalized cycle-safe learning paths, and provides contextual AI tutoring and interactive visualization via the Learning Atlas.

---

## Key Features

- **Multi-Format Ingestion & Synthesis (Phase 1 & 5)**: Ingests PDF, PowerPoint (`.pptx`), Word (`.docx`), and Image diagrams (`.png`, `.jpg`, `.jpeg`) up to 3,000 pages with automated LLM curriculum synthesis into custom Knowledge Atlases.
- **Educational Knowledge Representation & NLP (Phase 2)**: Extracts canonical concepts, bloom taxonomy skills, and prerequisite relationships.
- **Learner Model & Bayesian Knowledge Tracing (Phase 3)**: Continuous tracking of concept mastery ($P(L)$) and uncertainty, with dynamic live Groq LLM question generation and zero hardcoded templates.
- **Comprehensive Concept Lessons & Study Guides**: In-depth pedagogical modules featuring theoretical overviews, intuitive mental models, core principles, step-by-step worked examples, and common misconceptions.
- **Knowledge Initialization & Gap Prioritization (Phase 4)**: Self-assessment onboarding, diagnostic quizzes restricted strictly to self-reported known concepts, 4-category gap detection (Low Mastery, Insufficient Evidence, Weak Prerequisite, High Downstream Impact), and cycle-safe learning path generation.
- **Validation, Reliability & Idempotency (Phase 5)**: Standardized validation bounds, 429 transient retry with dual-model fallback, recovery logging, and duplicate request idempotency tracking.
- **Student-Facing Application & Learning Atlas (Phase 6)**: Modern React + TypeScript + Tailwind CSS UI with progressive 4-level zoom knowledge graph, concept inspector (X-Ray), AI tutor, and source document library.

---

## Quick Start Guide

### Prerequisites

- **Python**: 3.12+
- **Node.js**: 18+ & npm
- **Git**: for cloning

### 1. Clone the Repository

```bash
git clone https://github.com/VasaShashank/LearnSense.git
cd LearnSense
```

### 2. Configure Environment (`.env`)

Create a `.env` file in the **root directory** (`LearnSense/.env`):

```env
# ─────────────────────────────────────────────────────────────
# Server & API Configuration
# ─────────────────────────────────────────────────────────────
PORT=8000
HOST=0.0.0.0
ALLOWED_ORIGINS=http://localhost:5173,http://localhost:3000

# ─────────────────────────────────────────────────────────────
# LLM Provider API Keys
# ─────────────────────────────────────────────────────────────
# Get a free key from https://console.groq.com/keys
# Model: openai/gpt-oss-120b (default) or any Groq-supported model
GROQ_API_KEY=your_groq_api_key_here

# Optional: OpenAI fallback (if Groq unavailable)
OPENAI_API_KEY=your_openai_api_key_here

# ─────────────────────────────────────────────────────────────
# LLM Execution Mode
# ─────────────────────────────────────────────────────────────
# mock  = Deterministic test double (default for tests, no API calls, no cost)
# live  = Real LLM provider calls (requires valid GROQ_API_KEY)
#LLM_MODE=mock
```

**Important**: 
- For **development/testing**: Leave `LLM_MODE=mock` (or omit it). The mock adapter generates schema-shaped responses from your uploaded material — no API key required.
- For **real question generation**: Set `LLM_MODE=live` and provide a valid `GROQ_API_KEY`.
- The mock mode is used by all automated tests (`pytest`) to ensure hermetic, zero-cost runs.

### 3. Install & Run Backend

```bash
# From the root directory (LearnSense/)
pip install -r requirements.txt

# Mock mode (default - no API key needed)
$env:LLM_MODE="mock"          # PowerShell
# export LLM_MODE=mock        # Linux/macOS/Git Bash

uvicorn backend.app:app --host 0.0.0.0 --port 8000 --reload

# Live mode (real LLM)
$env:LLM_MODE="live"
uvicorn backend.app:app --host 0.0.0.0 --port 8000 --reload
```

- API: `http://localhost:8000`
- Swagger docs: `http://localhost:8000/docs`
- Health check: `http://localhost:8000/health`

### 4. Install & Run Frontend

```bash
cd frontend
npm install
npm run dev -- --port 5173
```

- App: `http://localhost:5173`
- The Vite dev server proxies `/api/*` to the backend automatically.

---

## LLM Modes Explained

| Mode | Environment | API Calls | Cost | Use Case |
|------|-------------|-----------|------|----------|
| **mock** | `LLM_MODE=mock` | **None** | $0 | Development, CI, testing, demo |
| **live** | `LLM_MODE=live` | Groq (`openai/gpt-oss-120b`) | Pay per token | Production, real question generation |

### Mock Adapter Behavior
- Located at `tests/support/mock_llm.py`
- Deterministic: same prompt → same response
- Generates grounded-looking questions with citations
- Questions are **placeholder-style** ("According to the source material regarding X...")
- Validates the full pipeline wiring without network calls

### Live Adapter Behavior
- Uses `GROQ_API_KEY` from `.env`
- Model configurable via `GROQ_MODEL` (default: `openai/gpt-oss-120b`)
- Questions are generated from actual retrieved passages
- Citations resolve to real page/block locations in your PDF

---

## Running Tests

### Backend (pytest)
```bash
# From root directory
# Tests force LLM_MODE=mock via tests/conftest.py
python -m pytest -q
```

**Expected**: 179 passed, 0 failed, 0 skipped

### Frontend (TypeScript + Build)
```bash
cd frontend
npx tsc --noEmit   # Type check
npm run build      # Production build
```

---

## Project Structure

```
LearnSense/
├── backend/                 # FastAPI application
│   ├── app.py              # FastAPI entrypoint + CORS
│   ├── routes/
│   │   └── api.py          # 25 REST endpoints
│   └── services/
│       ├── learning_service.py    # Question bank, BKT, diagnostics
│       ├── knowledge_build_service.py  # Phase 1→2→3 pipeline
│       ├── source_service.py      # Document listing/upload
│       ├── tutor_service.py       # AI tutoring
│       └── learner_service.py     # Learner state
├── phase1-5/               # Core pipeline (ingestion → EKR → questions)
│   ├── phase1/             # PDF → structured document
│   ├── phase2/             # Structured doc → EKR
│   ├── phase3/             # EKR → LearningContext, QuestionBank, BKT
│   ├── phase4/             # Learner initialization, gaps, paths
│   └── phase5/             # Validation, retry, idempotency
├── frontend/               # React + TypeScript + Vite
│   ├── src/
│   │   ├── api/client.ts   # Typed API client
│   │   ├── components/     # UI components
│   │   │   ├── navigation/TopNavbar.tsx
│   │   │   ├── sources/SourceLibrary.tsx
│   │   │   ├── session/LearningSession.tsx
│   │   │   └── ...
│   │   └── App.tsx         # Main app with view routing
│   └── package.json
├── storage/                # Local persisted data (gitignored)
│   ├── documents/          # Structured documents + assets
│   ├── learning_contexts/  # Phase 3 LearningContext JSON
│   ├── question_banks/     # Per-document question banks
│   └── jobs/               # Async upload job state
├── tests/
│   ├── conftest.py         # Fixtures + LLM_MODE=mock
│   ├── integration/        # E2E user journey tests
│   └── unit/               # Unit tests
└── requirements.txt
```

---

## Common Workflows

### Upload a Document & Generate Questions

1. Open `http://localhost:5173`
2. Click **+ Ingest** (top-right) → **Sources** view opens
3. Click **Ingest New Document** → select PDF/PPTX/DOCX
4. Wait for "Ingestion Succeeded" banner
5. Click **Open in Atlas** → navigate to a concept
6. Click **Practice** tab → grounded MCQ appears

### Switch LLM Mode at Runtime

```bash
# Stop backend (Ctrl+C), then:
$env:LLM_MODE="live"    # or "mock"
uvicorn backend.app:app --host 0.0.0.0 --port 8000 --reload
```

No frontend rebuild needed — the API contract is identical.

---

## Troubleshooting

| Issue | Fix |
|-------|-----|
| **Blank/pale screen after upload** | Fixed in `f7d101e` — title was an object, now extracted as string |
| **No questions for a concept** | Concept lacks retrievable evidence; upload richer material |
| **CORS errors** | Ensure `ALLOWED_ORIGINS` in `.env` includes your frontend URL |
| **Port 8000/5173 in use** | `Get-Process -Id (Get-NetTCPConnection -LocalPort 8000).OwningProcess \| Stop-Process -Force` |
| **Tests fail with "LIVE LLM call"** | Ensure `LLM_MODE=mock` in environment or run via `pytest` (sets it automatically) |

---

## Security Notes

- **No authentication** in this version — `learner_id` is caller-supplied (default: `student_alex`)
- **Process-local locks** — not safe for multi-worker deployments
- **No browser E2E tests** — Playwright/Cypress not configured
- **Mock mode only in CI** — live provider never called during automated tests

---

## License

Proprietary — TAPROOT Adaptive Learning Platform.

---

## Documentation Links

- [OPERATING_GUIDE.md](./OPERATING_GUIDE.md) — Step-by-step user and developer operating instructions
- [ARCHITECTURE.md](./ARCHITECTURE.md) — Technical architecture, pipeline data flow, system design
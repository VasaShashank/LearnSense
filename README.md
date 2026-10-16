# TAPROOT / LearnSense — Adaptive Learning Platform & Institutional Hub

TAPROOT / LearnSense is an enterprise-ready, local-first, CPU-friendly AI adaptive learning platform and institutional intelligence system. It transforms educational documents (textbooks, slide decks, PDFs, lecture notes, diagrams) into structured knowledge graphs, tracks learner mastery using Bayesian Knowledge Tracing (BKT), diagnoses knowledge gaps, generates personalized cycle-safe learning paths, and provides contextual AI tutoring, interactive visualization via the Learning Atlas, automated teacher intervention planning, and multi-tenant institutional administration.

---

## 🌟 Key Platform Features

### 1. Multi-Format Ingestion & Synthesis (Phases 1 & 5)
- **Broad File Support**: Ingests PDF, PowerPoint (`.pptx`), Word (`.docx`), Markdown (`.md`), and Image diagrams (`.png`, `.jpg`, `.jpeg`).
- **High-Capacity Ingestion**: Supports full college textbooks up to **3,000 pages** and 500 MB without truncation.
- **Table & Note Fidelity**: Extracts PowerPoint tables with full grid layouts, slide speaker notes (`role="speaker_notes"`), and real coordinate bounding boxes.
- **Automated Curriculum Synthesis**: Analyzes uploaded materials to automatically synthesize subject titles, 8–14 foundational concepts, formal definitions, and prerequisite dependencies.

### 2. Educational Knowledge Representation & Strict DAG Topology (Phase 2)
- **9-Stage Deterministic Pipeline**: Tokenizes text, classifies educational roles (`definition`, `theorem`, `formula`, `worked_example`, `exercise`), resolves entities, and extracts concepts.
- **Strict DAG Guarantee**: Applies Tarjan's Strongly Connected Components (SCC) algorithm and deterministic cycle-breaking to prevent circular prerequisite links.
- **Semantic Topic Extractor**: Groups concepts into macro pedagogical territories (`Foundations`, `Core Principles`, `Advanced Applications`) with subheading DAG navigation.

### 3. Learner Modeling & Bayesian Knowledge Tracing (Phase 3)
- **Bayesian Knowledge Tracing (BKT)**: Continuous tracking of concept mastery ($P(L_t)$) with bounded certainty ($0.01 \le P(L) \le 0.99$).
- **Dynamic Live LLM Question Engine**: Generates real domain questions, correct answers, and distractors via Groq (LLaMA 3.3 70B / GPT-OSS 120B) with dual-model burst retry and zero hardcoded templates.
- **Pedagogical Study Modules**: In-depth conceptual guides featuring intuitive mental models, core mathematical rules, step-by-step worked examples, and common student traps.
- **Notation-Matched Video Recommendations**: Matches subject concepts and mathematical notation (e.g., Leibniz vs. Lagrange) with verified educational videos from Khan Academy, 3Blue1Brown, and MIT OpenCourseWare.

### 4. Initialization, Gap Prioritization & Path Planning (Phase 4)
- **Diagnostic Protocol**: Self-assessment onboarding (`KNOW`, `DONT_KNOW`, `UNANSWERED`) with diagnostic quizzes restricted strictly to self-reported known concepts. If no concepts are marked known, diagnostics are bypassed without score penalty.
- **4-Category Knowledge Gap Classification**: Detects `LOW_MASTERY`, `INSUFFICIENT_EVIDENCE`, `WEAK_PREREQUISITE`, and `HIGH_DOWNSTREAM_IMPACT`.
- **Topological Planner**: Kahn's algorithm-based cycle-safe planner selecting active next learning targets.

### 5. Multi-Persona Experiences & User Workspaces (Phase 6)
- **Role Switcher**: Seamlessly switch between three primary roles:
  - 🎓 **Student Experience**: Interactive Learning Atlas (`@xyflow/react`), Topic Cluster Nodes, Subheading DAG navigation, X-Ray Concept Inspector, Study Sessions, and Contextual AI Tutor.
  - 🧑‍🏫 **Teacher Hub (`TeacherDashboard.tsx`)**: Class-wide concept mastery heatmaps, struggling student rosters, automated collective teaching optimizer, and FERPA-compliant de-identification mode.
  - 🏛️ **B2B Institutional Portal (`InstitutionalPortal.tsx`)**: Multi-tenant organization management, seat license utilization, department rosters, and cohort learning gain benchmarks.

### 6. Validation, Reliability & Zero-Fallback Policy (Phase 5)
- Standardized validation bounds, 429 transient retry with dual-model fallback, recovery logging, and duplicate request idempotency tracking.
- Strict no-fallback engineering posture: zero synthetic placeholders or error-swallowing in production.

---

## 🚀 Quick Start Guide

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
Create a `.env` file in the root directory (`LearnSense/.env`):
```env
# Server & API Configuration
PORT=8000
HOST=0.0.0.0
ALLOWED_ORIGINS=http://localhost:5173,http://localhost:3000

# Live LLM Provider Configuration (Groq recommended)
# Get a free API key from https://console.groq.com/keys
GROQ_API_KEY=your_groq_api_key_here
GROQ_MODEL=openai/gpt-oss-120b

# Optional: OpenAI fallback
OPENAI_API_KEY=your_openai_api_key_here

# Execution Mode: "live" for real LLM, "mock" for zero-cost offline development
LLM_MODE=mock
```

### 3. Install & Run Backend
```bash
# Install Python dependencies
pip install -r requirements.txt

# Run backend with mock LLM (offline / testing)
$env:LLM_MODE="mock"          # Windows PowerShell
uvicorn backend.app:app --host 0.0.0.0 --port 8000 --reload

# Or run with live Groq LLM (production / real questions)
$env:LLM_MODE="live"
uvicorn backend.app:app --host 0.0.0.0 --port 8000 --reload
```
- API Documentation (Swagger): `http://localhost:8000/docs`
- Health Check: `http://localhost:8000/health`

### 4. Install & Run Frontend
```bash
cd frontend
npm install
npm run dev -- --port 5173
```
- Web Application: `http://localhost:5173`

---

## 👥 Personas & Workspaces

| Persona | Primary View | Key Capabilities |
|---|---|---|
| **Student** | **Learning Atlas** | Topic clusters, concept nodes, study guide tabs, adaptive quizzes, AI tutor |
| **Educator / Teacher** | **Teacher Hub** | Class heatmaps, FERPA de-identification, collective teaching optimizer, intervention planner |
| **Institutional Admin** | **Institutional Portal** | Multi-tenant organization metrics, seat allocation, department rosters, cohort analytics |

---

## 🧪 Testing & Verification

### Backend Regression Suite (pytest)
```bash
# Runs full unit, integration, and security suites in hermetic mock mode
python -m pytest -v
```

### Static No-Fallback Ast Guard
```bash
python -m pytest tests/unit/test_no_fallbacks.py
```

### Live Feature Probe
```bash
python scripts/verify_features.py
```

### Frontend Typecheck & Production Build
```bash
cd frontend
npx tsc --noEmit
npm run build
```

---

## 📁 Repository Structure

```text
LearnSense/
├── backend/                     # FastAPI backend application
│   ├── app.py                  # Server entrypoint and middleware
│   ├── routes/                 # REST API endpoints (learning, teacher, institution)
│   └── services/               # Authoritative business logic services
├── extraction/                  # Multi-format document extraction engines
├── frontend/                    # Modern React 19 + TypeScript + Vite frontend
│   └── src/
│       ├── components/atlas/   # React Flow atlas, concept & topic cluster nodes
│       ├── components/teacher/ # Educator dashboard & intervention generator
│       └── components/institution/ # Multi-tenant administrative portal
├── ingestion/                   # Document inspection, coordinate mapping & pipeline
├── phase2/                      # 9-stage EKR pipeline & Semantic Topic Extractor
├── phase3/                      # BKT learner modeling, question bank, BM25 retrieval
├── phase4/                      # Knowledge gaps, planning, teacher optimizer, institution
├── phase5/                      # Validation boundaries, idempotency, security
├── storage/                     # Durable filesystem repositories & JSON records
└── tests/                       # Unit, integration, and security test suites
```

---

## 📖 Key Documentation Links

- [OPERATING_GUIDE.md](./OPERATING_GUIDE.md) — Detailed user & administrator operating manual.
- [ARCHITECTURE.md](./ARCHITECTURE.md) — System architecture and end-to-end dataflow.
- [IMPLEMENTED_SYSTEM_ARCHITECTURE.md](./IMPLEMENTED_SYSTEM_ARCHITECTURE.md) — Full technical accounting across all phases.
- [CHANGES_SUMMARY.md](./CHANGES_SUMMARY.md) — Changelog of recent platform features and enhancements.
- [FEATURE_VERIFICATION_REPORT.md](./FEATURE_VERIFICATION_REPORT.md) — Automated live feature execution report.
- [frontend/README.md](./frontend/README.md) — Frontend architecture and component hierarchy.
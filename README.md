# TAPROOT — Adaptive Learning Platform

TAPROOT is a local-first, CPU-friendly AI adaptive learning platform that transforms educational documents (textbooks, PDFs, notes) into structured knowledge graphs, tracks learner mastery using Bayesian Knowledge Tracing (BKT), diagnoses knowledge gaps, generates personalized cycle-safe learning paths, and provides contextual AI tutoring and interactive visualization via the Learning Atlas.

---

## Key Features

- **Document Ingestion & Extraction (Phase 1)**: Robust PDF parsing, multi-column detection, and image asset extraction.
- **Educational Knowledge Representation & NLP (Phase 2)**: Extracts canonical concepts, bloom taxonomy skills, and prerequisite relationships.
- **Learner Model & Bayesian Knowledge Tracing (Phase 3)**: Continuous tracking of concept mastery ($P(L)$) and uncertainty, with adaptive question generation and evaluation.
- **Knowledge Initialization & Gap Prioritization (Phase 4)**: Self-assessment onboarding, diagnostic quizzes restricted strictly to self-reported known concepts, 4-category gap detection (Low Mastery, Insufficient Evidence, Weak Prerequisite, High Downstream Impact), and cycle-safe learning path generation.
- **Validation, Reliability & Idempotency (Phase 5)**: Standardized validation bounds, retry handlers, recovery logging, and duplicate request idempotency tracking.
- **Student-Facing Application & Learning Atlas (Phase 6)**: Modern React + TypeScript + Tailwind CSS UI with progressive 4-level zoom knowledge graph, concept inspector (X-Ray), AI tutor, and source document library.

---

## Quick Start Guide

### Prerequisites

- **Python**: 3.12+
- **Node.js**: 18+ & npm

### Developer Environment Setup (`.env`)

Create a `.env` file in the root directory:

```env
# Server & API Configuration
PORT=8000
HOST=0.0.0.0
ALLOWED_ORIGINS=http://localhost:5173,http://localhost:3000

# Optional LLM Provider API Keys (Falls back automatically to mock schemas if omitted)
GROQ_API_KEY=your_groq_api_key_here
OPENAI_API_KEY=your_openai_api_key_here
```

### 1. Install Backend Dependencies & Run Backend

```bash
# Install Python packages
pip install -r requirements.txt

# Start FastAPI Backend Server
uvicorn backend.app:app --host 0.0.0.0 --port 8000 --reload
```

The API will be accessible at `http://localhost:8000` with documentation at `http://localhost:8000/docs`.

### 2. Install Frontend Dependencies & Run Frontend

```bash
# Navigate to frontend directory
cd frontend

# Install Node dependencies
npm install

# Start Vite Development Server
npm run dev
```

The web application will be accessible at `http://localhost:5173`.

---

## Running Tests

### Backend Test Suite (Pytest)

Run all unit, integration, failure, security, and E2E journey tests:

```bash
python3 -m pytest
```

### Frontend Production Build Check

```bash
cd frontend
npm run build
```

---

## Documentation Links

- [OPERATING_GUIDE.md](./OPERATING_GUIDE.md) — Step-by-step user and developer operating instructions for using all features on the web application.
- [ARCHITECTURE.md](./ARCHITECTURE.md) — Comprehensive technical architecture, pipeline data flow, and system design specifications.

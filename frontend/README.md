# LearnSense — Frontend Application

Modern React 19 + TypeScript + Vite web application powering the **LearnSense / TAPROOT** adaptive learning experience.

---

## 🌟 Key Subsystems & User Interfaces

### 1. Interactive Learning Atlas (`src/components/atlas/`)
Built with [`@xyflow/react`](https://reactflow.dev/) (React Flow) for rendering dynamic, accessible, interactive knowledge graphs:
- **`CustomConceptNode.tsx`**: Renders individual concept nodes with real-time Bayesian Knowledge Tracing (BKT) mastery coloring (Emerald for Mastered $\ge 0.75$, Amber for Developing $0.40$–$0.74$, Slate for Unlearned $< 0.40$), status badges, uncertainty indicators, and action triggers.
- **`TopicClusterNode.tsx`**: Groups related concepts into coherent pedagogical territories (Foundational, Core Principles, Advanced Applications) with aggregate mastery progress bars.
- **`SubheadingNode.tsx`**: Provides hierarchical chapter and section DAG navigation, connecting syllabus outlines directly to concept graphs.
- **`atlasIntelligence.ts`**: Client-side graph intelligence engine computing path distance, bottleneck concepts, prerequisite coverage, and topological clusters.
- **Canvas Annotations (`src/utils/annotationStorage.ts`)**: Supports user notes, pins, and custom highlighted territories stored locally.

### 2. Multi-Persona Workspace & Role Switcher
Supports three distinct personas accessible via the **Persona Switcher** in the navigation bar (`LoginPersonaModal.tsx`):
- **Student Persona**:
  - Personalized Learning Atlas & adaptive next target recommendation.
  - Step-by-step diagnostic onboarding workflow (`OnboardingWorkflow.tsx`).
  - Study modules with intuitive mental models, worked examples, and practice quizzes (`LearningSession.tsx`).
  - Real-time Contextual AI Tutor with citations (`ContextualTutor.tsx`).
- **Educator / Teacher Persona (`TeacherDashboard.tsx`)**:
  - Class-wide concept mastery heatmaps and struggling student rosters.
  - **Standalone Educator Mode**: Private class management with full FERPA-compliant student de-identification.
  - **Automated Teaching Optimizer**: AI-driven intervention lesson plans with targeted curriculum activities and notation-matched external video recommendations (Khan Academy, 3Blue1Brown, MIT OCW).
- **Institutional Admin Persona (`InstitutionalPortal.tsx`)**:
  - Multi-tenant organization dashboard with department and course breakdowns.
  - Seat license utilization tracking and instructor assignment.
  - Enterprise-grade cohort analytics and learning gain benchmarks.

### 3. Concept Inspector & X-Ray (`src/components/inspector/`)
- **`ConceptInspector.tsx`**: Side drawer revealing in-depth pedagogical metadata:
  - Canonical name, Bloom's Taxonomy skill level, and primary definition.
  - Mathematical mastery probability ($P(L)$) and Bayesian uncertainty metric.
  - Upstream prerequisites and downstream impacted concepts.
  - Verbatim source citations (exact document, page number, block excerpt).

### 4. Interactive Learning Session (`src/components/session/`)
- **`LearningSession.tsx`**: Dedicated dual-mode study environment:
  - **Study Guide Tab**: High-yield conceptual theory, intuitive real-world mental models, core mathematical rules, step-by-step worked examples, and common misconceptions.
  - **Adaptive Quiz Tab**: Authoritative server-evaluated practice questions with grounded explanations.

---

## 🚀 Quick Start Guide

### Prerequisites
- **Node.js**: 18+ (Node 20+ recommended)
- **npm**: 9+

### Installation & Development
```bash
# From the frontend/ directory
npm install

# Start Vite dev server on port 5173
npm run dev -- --port 5173
```

The application will be accessible at `http://localhost:5173`.  
The Vite dev server proxies `/api/*` endpoints to the FastAPI backend at `http://localhost:8000`.

### Production Build & Linting
```bash
# Typecheck and build production bundle
npm run build

# Run Oxlint / ESLint rules
npm run lint

# Preview production build locally
npm run preview
```

---

## 📁 Directory Structure

```text
frontend/src/
├── api/
│   └── client.ts                    # Typed API client for FastAPI backend
├── components/
│   ├── atlas/                       # React Flow canvas, concept nodes, clusters & DAGs
│   │   ├── CustomConceptNode.tsx    # BKT-colored concept node
│   │   ├── TopicClusterNode.tsx     # Macro pedagogical cluster container
│   │   ├── SubheadingNode.tsx       # Chapter & section outline node
│   │   ├── LearningAtlas.tsx        # Atlas canvas with minimap & zoom controls
│   │   └── atlasIntelligence.ts    # Graph metrics & topology heuristics
│   ├── common/                      # Reusable modals, badges, persona switcher
│   ├── inspector/                   # Concept X-Ray drawer with citations
│   ├── institution/                 # Institutional multi-tenant admin portal
│   ├── navigation/                  # Top navbar, subject switcher, role menu
│   ├── onboarding/                  # Multi-format uploader & diagnostic quiz
│   ├── session/                     # Study guide modules & practice quizzes
│   ├── teacher/                     # Educator dashboard & intervention planner
│   └── tutor/                       # Contextual AI tutor chat with source cards
├── types/
│   └── api.ts                       # Shared TypeScript interfaces & DTOs
└── utils/
    ├── annotationStorage.ts         # Local canvas note & bookmark persistence
    └── conceptName.ts               # Name normalization & sanitization
```

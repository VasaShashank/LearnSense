# TAPROOT — Web Application Operating Guide

This guide explains how to configure, start, and operate all features on the Taproot website from both the **Developer Side** and the **User Side**.

---

## 1. DEVELOPER SETUP & CONFIGURATION

### Step 1.1: Environment Configuration (`.env`)

In the project root directory, create or edit the `.env` file:

```env
# API Server Configuration
PORT=8000
HOST=0.0.0.0
ALLOWED_ORIGINS=http://localhost:5173,http://localhost:3000

# Developer API Keys for Live LLM Question & Tutor Generation (Optional)
# If no keys are provided, TAPROOT automatically falls back to local schema-based generation.
GROQ_API_KEY=gsk_your_groq_api_key_here
OPENAI_API_KEY=sk-proj-your_openai_api_key_here
```

### Step 1.2: Launch Backend and Frontend

**Terminal 1 (Backend Server):**
```bash
pip install -r requirements.txt
uvicorn backend.app:app --host 0.0.0.0 --port 8000 --reload
```

**Terminal 2 (Frontend Application):**
```bash
cd frontend
npm install
npm run dev
```

Open `http://localhost:5173` in your web browser.

---

## 2. USER OPERATING GUIDE — WEBSITE FEATURES

### Feature 1: Subject Selection & Material Ingestion
1. **View Available Subjects**: Upon opening the application, the top bar displays available learning subjects (e.g., *Calculus*, *Machine Learning*, *Linear Algebra*).
2. **Upload New Course Material**:
   - Navigate to the **Sources** tab.
   - Drag and drop or select a PDF textbook/notes document.
   - Click **Upload**. TAPROOT will validate the file (checking PDF validity, page limits, and corruption) and begin extracting educational concepts.

### Feature 2: Concept Onboarding & Diagnostic Quiz
1. **Self-Assessment**:
   - When starting a new subject, click **Start Onboarding**.
   - Review extracted concepts for the subject.
   - Mark concepts as:
     - `KNOW`: You feel familiar with this concept.
     - `DON'T KNOW`: You are unfamiliar with this concept.
     - `UNANSWERED`: Skip for now.
2. **Diagnostic Quiz**:
   - If you marked any concept as `KNOW`, TAPROOT generates a brief diagnostic quiz restricted **strictly** to those concepts.
   - If you selected `DON'T KNOW` for all concepts, the diagnostic quiz is skipped automatically, and TAPROOT initializes your learning path at the foundational root concepts without penalizing your mastery score.
   - Answer the diagnostic questions or select *"I don't know"*.
   - Click **Submit Diagnostic**.

### Feature 3: Learning Atlas (Knowledge Graph)
1. **Visual Knowledge Map**:
   - The main **Learning Atlas** displays interactive node territories representing concepts and directional arrows representing prerequisites.
2. **Color Code Indications**:
   - 🟢 **Green (Mastered)**: Mastery probability $\ge 0.75$.
   - 🟡 **Yellow (Developing)**: Mastery probability between $0.40$ and $0.74$.
   - 🔴 **Red / Orange (Needs Attention / Weak Prerequisite)**: Identified knowledge gap or root-cause prerequisite blocking downstream learning.
   - ⚪ **Gray (Unexplored / Neutral)**: Uninitialized or insufficient evidence.
   - 🔵 **Blue Ring (Active Next Target)**: Recommends your immediate next learning step.
3. **Controls**:
   - **Zoom & Pan**: Use scroll wheel or zoom controls in the corner.
   - **Accessible Structured View**: Click **List View / Accessible Tree** to view an accessible table breakdown of all concepts, prerequisites, and mastery scores.

### Feature 4: X-Ray Inspector & Downstream Impact
1. Click on any concept node in the Atlas.
2. The **Concept Inspector** side panel opens, showing:
   - Detailed definition and Bloom Taxonomy skill level.
   - Current Bayesian Knowledge Tracing (BKT) mastery probability and uncertainty.
   - Direct prerequisites and downstream dependent concepts.
   - Source citations (exact page, section, and textbook quotes).

### Feature 5: Interactive Learning Sessions & Mini-Quizzes
1. Click **Start Learning Session** on your active next target.
2. Review the structured explanation and worked example.
3. Complete practice questions:
   - Select your answer choice.
   - Click **Submit Answer**.
   - Immediate feedback and step-by-step explanations will be displayed.
   - Your mastery probability updates instantly in real time and is reflected on the Learning Atlas.

### Feature 6: Contextual AI Tutor
1. Click the **AI Tutor** icon on any concept card or inspector panel.
2. Select your desired guidance mode:
   - **Explain**: Step-by-step breakdown matched to your mastery level.
   - **Hint**: Targeted clue without spoiling the solution.
   - **Analogy**: Conceptual comparison to real-world objects.
   - **Why Wrong**: Common misconception analysis.
3. Or type a custom question in the chat box to converse with the contextual tutor with citations.

### Feature 7: Session Progress & State Persistence
- All progress, responses, and mastery levels automatically persist across page refreshes and server restarts via SQLite and atomic JSON storage.
- To continue where you left off, simply reopen the application.

### Feature 8: Persona Switching (Student, Educator, Institutional Admin)
1. Click the **Persona / Role Badge** in the top navigation bar.
2. Select one of the available personas:
   - **Student (Alex)**: Explores personalized knowledge graphs, takes diagnostic quizzes, and works through study guides.
   - **Educator (Prof. Vance)**: Accesses class cohorts, collective analytics, and automated intervention plans.
   - **Institutional Admin (Dean Sterling)**: Manages department-level seat allocations and institutional benchmarks.

### Feature 9: Teacher Hub & Collective Teaching Optimizer
1. Switch to the **Educator** persona or navigate to the **Teacher Hub** view.
2. **Class Overview & Mastery Heatmap**:
   - Select your target class cohort (e.g. *Calculus Cohort Alpha*).
   - Review class-wide concept mastery distributions, average mastery scores, and struggling student counts.
3. **FERPA De-Identification Toggle**:
   - Toggle **De-Identify Students** on to replace student names with anonymous identifiers (`Student #104`), ensuring privacy compliance during classroom projections or research.
4. **Generate Collective Intervention Plan**:
   - Click **Generate Teaching Intervention**.
   - The Teaching Optimizer identifies class-wide bottleneck concepts, recommends tailored classroom group activities, and assigns notation-matched external videos (Khan Academy, 3Blue1Brown, MIT OCW).
   - Click **Save Intervention Plan** to store and track the plan.

### Feature 10: B2B Institutional Portal
1. Switch to the **Institutional Admin** persona.
2. View organization statistics:
   - Total enrolled learners, faculty accounts, active courses, and departments.
   - Seat license quota tracker showing active vs. available licenses.
3. Manage departments and courses:
   - Review department-specific learning gains and cohort completion benchmarks.
   - Assign instructors and monitor cross-section performance.

### Feature 11: Multi-Format Ingestion & Synthesis (PDF, PPTX, DOCX, Images)
1. Go to **Sources** or click **+ Upload Material...** in the top bar.
2. Upload any supported format:
   - **PDF (`.pdf`)**: Up to 3,000 pages with full layout, table, and equation extraction.
   - **PowerPoint (`.pptx`)**: Slide outlines, table structures, speaker notes, and shape coordinates.
   - **Word (`.docx`)**: Heading hierarchies, body paragraphs, and tables.
   - **Diagrams / Images (`.png`, `.jpg`, `.jpeg`)**: Automatic visual document processing.
3. TAPROOT automatically parses the material, synthesizes a formal Subject Title, extracts canonical concepts, builds a strict DAG knowledge graph, and initializes your interactive Atlas.

### Feature 12: Subheading DAG Navigation, Topic Clusters & Canvas Annotations
1. **Topic Cluster Boundaries**: Concepts in the Learning Atlas are grouped into visual territory boundaries (`Foundations`, `Core Principles`, `Advanced Applications`).
2. **Subheading DAG Nodes**: Click on section and chapter outline nodes to expand and focus on specific sub-domains.
3. **Canvas Annotations**: Add notes, pins, and highlights directly onto the Atlas canvas, automatically persisted in local browser storage.


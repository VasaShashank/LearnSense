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
3. Or type a custom question in the chat box to converse with the contextual tutor.

### Feature 7: Session Progress & State Persistence
- All progress, responses, and mastery levels automatically persist across page refreshes and server restarts.
- To continue where you left off, simply reopen the application.

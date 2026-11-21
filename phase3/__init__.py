"""Phase 3 — Unified Adaptive Learning, AKT Knowledge Tracing, and Personalization System.

Integrates Person 3's authoritative v1.0.2 release:
- Model 5 v5.2.1 AKT Neural Mastery Engine (PyTorch, 87-concept canonical vocabulary)
- Canonical Concept Migration Adapter (deterministic resolution of legacy simulator IDs)
- Expected Information Gain (EIG) Adaptive Assessment Engine & Computerized Adaptive Testing
- SymPy Symbolic Solution Verifier & Diagram Detection
- Micro-Quiz Engine with Distractor Quality and Single-Answer Validation
- 7-Mode Socratic Tutoring Engine with Pedagogical Guardrails & Anti-Leak Defenses
- Grounded NCERT Knowledge Base with Authentic Page Citations
- DAG-Constrained Study Planner & Spaced Review Scheduler
- Personalized Multi-Modal Recommendation Engine
- Unified LearnSensePersonalizationService Facade
"""

from phase3.akt.akt_inference import (
    AKTMasteryInferenceService,
    LearnerInteraction,
)
from phase3.akt.migration_adapter import (
    CanonicalConceptMigrationAdapter,
    CURRICULUM_ID,
    CURRICULUM_VERSION,
    CURRICULUM_FINGERPRINT,
)
from phase3.assessment.adaptive_assessment import (
    AdaptiveAssessmentSelector,
    AdaptiveAssessmentSession,
)
from phase3.assessment.solution_verifier import (
    SolutionVerifier,
    SolutionVerificationResult,
)
from phase3.quiz.micro_quiz import (
    MicroQuizEngine,
    MicroQuizSession,
)
from phase3.tutoring.tutoring import (
    TutoringEngine,
    TutoringRequest,
    TutoringResponse,
)
from phase3.tutoring.teacher import (
    IndependentTeacherPlanner,
    CohortTeacherManager,
    SocraticTeacher,
)
from phase3.tutoring.knowledge_base import (
    GroundedKnowledgeBase,
)
from phase3.planning.study_plan import (
    StudyPlanGenerator,
    PersonalizedStudyPlan,
)
from phase3.recommendation.recommendation import (
    RecommendationEngine,
    RecommendationItem,
)
from phase3.service import LearnSensePersonalizationService

__all__ = [
    "AKTMasteryInferenceService",
    "LearnerInteraction",
    "CanonicalConceptMigrationAdapter",
    "CURRICULUM_ID",
    "CURRICULUM_VERSION",
    "CURRICULUM_FINGERPRINT",
    "AdaptiveAssessmentSelector",
    "AdaptiveAssessmentSession",
    "SolutionVerifier",
    "SolutionVerificationResult",
    "MicroQuizEngine",
    "MicroQuizSession",
    "TutoringEngine",
    "TutoringRequest",
    "TutoringResponse",
    "IndependentTeacherPlanner",
    "SocraticTeacher",
    "CohortTeacherManager",
    "GroundedKnowledgeBase",
    "StudyPlanGenerator",
    "PersonalizedStudyPlan",
    "RecommendationEngine",
    "RecommendationItem",
    "LearnSensePersonalizationService",
]

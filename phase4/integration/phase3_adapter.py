"""
Phase 3 Adapter for Phase 4 Planning.
Connects Phase 4 planning loop with Phase 3 KnowledgeTracer, LearningContext,
QuestionBank, and LLM Content Generation interfaces.
"""

from typing import Dict, List, Optional, Tuple
from phase3.adapters.llm_adapter import Phase3LLMAdapter
from phase3.knowledge.phase2_adapter import LearningContext
from phase3.learner.kt import KnowledgeTracer
from phase3.learner.models import LearnerState
from phase3.question_bank.models import QuestionBank
from phase4.gaps.gap_detector import GapDetector
from phase4.gaps.gap_prioritizer import GapPrioritizer
from phase4.knowledge_initialization.concept_self_assessment import ConceptSelfAssessmentHandler
from phase4.knowledge_initialization.diagnostic_orchestrator import DiagnosticOrchestrator
from phase4.knowledge_initialization.knowledge_sufficiency import KnowledgeSufficiencyChecker
from phase4.models import (
    ActivityType,
    KnowledgeGap,
    LearningActivity,
    LearningPath,
    LearningTarget,
)
from phase4.planning.learning_path_generator import LearningPathGenerator
from phase4.planning.next_target_selector import NextTargetSelector


class Phase3Adapter:
    """Facade adapter bridging Phase 4 planning with Phase 3 components."""

    def __init__(
        self,
        tracer: Optional[KnowledgeTracer] = None,
        llm_adapter: Optional[Phase3LLMAdapter] = None,
        self_assessment_handler: Optional[ConceptSelfAssessmentHandler] = None,
        sufficiency_checker: Optional[KnowledgeSufficiencyChecker] = None,
        diagnostic_orchestrator: Optional[DiagnosticOrchestrator] = None,
        gap_detector: Optional[GapDetector] = None,
        gap_prioritizer: Optional[GapPrioritizer] = None,
        path_generator: Optional[LearningPathGenerator] = None,
        target_selector: Optional[NextTargetSelector] = None,
    ):
        self.tracer = tracer or KnowledgeTracer()
        self.llm_adapter = llm_adapter or Phase3LLMAdapter()
        self.self_assessment_handler = self_assessment_handler or ConceptSelfAssessmentHandler()
        self.sufficiency_checker = sufficiency_checker or KnowledgeSufficiencyChecker()
        self.diagnostic_orchestrator = diagnostic_orchestrator or DiagnosticOrchestrator(tracer=self.tracer)
        self.gap_detector = gap_detector or GapDetector()
        self.gap_prioritizer = gap_prioritizer or GapPrioritizer()
        self.path_generator = path_generator or LearningPathGenerator(
            detector=self.gap_detector, prioritizer=self.gap_prioritizer
        )
        self.target_selector = target_selector or NextTargetSelector()

    def handle_activity_response_and_replan(
        self,
        learner_state: LearnerState,
        learning_context: LearningContext,
        subject_concept_ids: List[str],
        concept_ids: List[str],
        correctness: float,
    ) -> Tuple[Dict[str, float], LearningPath, Optional[LearningTarget]]:
        """
        Executes adaptive loop:
        1. Updates Phase 3 KT model from learner activity correctness
        2. Recalculates Phase 4 gaps & reprioritizes
        3. Generates updated personalized learning path
        4. Selects next learning target
        """
        # Step 1: Phase 3 KT Update
        updated_masteries = self.tracer.update(
            learner_state=learner_state,
            concept_ids=concept_ids,
            correctness=correctness,
        )

        # Step 2 & 3: Phase 4 Re-planning
        path = self.path_generator.generate_path(
            learning_context=learning_context,
            learner_state=learner_state,
            subject_concept_ids=subject_concept_ids,
        )

        # Step 4: Next target selection
        next_target = self.target_selector.select_next_target(
            learning_path=path,
            learner_state=learner_state,
            learning_context=learning_context,
        )

        return updated_masteries, path, next_target

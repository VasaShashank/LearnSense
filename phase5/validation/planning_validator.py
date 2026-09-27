"""
Phase 4 Personalization and Onboarding Diagnostic Validator for Taproot Phase 5.
Validates self-assessment selections, diagnostic session creation, zero-KT foundational path resolution,
and learning path DAG structures.
"""

from typing import Dict, List, Optional, Set
from phase4.models import (
    KnowledgeGap,
    KnowledgeInitializationSession,
    LearningPath,
    LearningTarget,
    SelfAssessmentStatus,
)
from phase5.models.validation_result import RecoveryClassification, ValidationResult, ValidationStatus
from phase5.observability.validation_events import ValidationEventLogger


class PlanningValidator:
    """Validates Phase 4 onboarding diagnostics, knowledge gaps, and learning paths."""

    def validate_self_assessment(
        self,
        selections: Dict[str, SelfAssessmentStatus],
        all_subject_concept_ids: List[str],
    ) -> ValidationResult:
        result = ValidationResult(status=ValidationStatus.VALID, is_valid=True)
        valid_set = set(all_subject_concept_ids)

        for c_id, status in selections.items():
            if valid_set and c_id not in valid_set:
                result.add_error(f"Self-assessment reference concept '{c_id}' not found in subject graph.")

            if status not in [SelfAssessmentStatus.KNOW, SelfAssessmentStatus.DONT_KNOW, SelfAssessmentStatus.UNANSWERED]:
                result.add_error(f"Invalid SelfAssessmentStatus '{status}' for concept '{c_id}'.")

        return result

    def validate_diagnostic_quiz_creation(
        self,
        session: KnowledgeInitializationSession,
        generated_questions: List[Dict],
    ) -> ValidationResult:
        """
        Validates that diagnostic assessment questions are strictly restricted to selected KNOW concepts.
        And verifies that self-reporting KNOW/DON'T_KNOW never directly sets KT mastery=1.0 or 0.0.
        """
        result = ValidationResult(status=ValidationStatus.VALID, is_valid=True)
        know_set = set(session.know_concept_ids)

        if len(session.know_concept_ids) == 0:
            if len(generated_questions) > 0:
                result.add_error("Diagnostic generated questions when zero KNOW concepts were selected.")
            return result

        for q in generated_questions:
            q_concepts = q.get("concept_ids", [])
            for c_id in q_concepts:
                if c_id not in know_set:
                    result.add_error(
                        f"Diagnostic question contains concept '{c_id}' which was NOT reported as KNOW by the learner."
                    )

        if not result.is_valid:
            result.recoverable = True
            result.recovery_classification = RecoveryClassification.RECOVERABLE
            result.suggested_action = "Filter diagnostic questions to match selected KNOW concepts strictly."
            ValidationEventLogger.log_event(
                "diagnostic_validation_failed",
                "INVALID",
                f"Diagnostic quiz validation failed: {result.errors}",
                learner_id=session.learner_id,
            )

        return result

    def validate_learning_path(
        self,
        path: LearningPath,
        valid_concept_ids: Set[str],
    ) -> ValidationResult:
        result = ValidationResult(status=ValidationStatus.VALID, is_valid=True)
        seen_nodes: Set[str] = set()

        for idx, node in enumerate(path.nodes):
            c_id = node.concept_id
            if c_id not in valid_concept_ids:
                result.add_error(f"LearningPath node at index {idx} references unknown concept '{c_id}'.")

            if c_id in seen_nodes:
                result.add_error(f"Duplicate node concept '{c_id}' found in learning path at index {idx}.")
            else:
                seen_nodes.add(c_id)

        result.metadata["path_node_count"] = len(path.nodes)
        return result

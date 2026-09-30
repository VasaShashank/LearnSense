"""
Concept Self-Assessment Handler.
Processes self-reported KNOW / DONT_KNOW / UNANSWERED concept selections.
Maintains clear separation: self-reported status does NOT directly become KT mastery probability.
"""

from typing import Dict, List, Optional
import uuid
from phase4.models import (
    ConceptSelfAssessment,
    ConfidenceLevel,
    KnowledgeInitializationSession,
    SelfAssessmentStatus,
    KnowledgeSufficiencyStatus,
)


class ConceptSelfAssessmentHandler:
    """Manages concept self-assessment creation and category partitioning."""

    def create_session(
        self,
        learner_id: str,
        subject_id: str,
        selections: Dict[str, SelfAssessmentStatus],
        all_subject_concept_ids: List[str],
        confidences: Optional[Dict[str, ConfidenceLevel]] = None,
    ) -> KnowledgeInitializationSession:
        """
        Creates a new KnowledgeInitializationSession partitioning subject concepts
        into KNOW, DONT_KNOW, and UNANSWERED.

        ``confidences`` is stored as a SEPARATE signal on each assessment and in
        ``session.confidences``. It never becomes KT mastery (Batch 5).
        """
        assessments: Dict[str, ConceptSelfAssessment] = {}
        know_ids: List[str] = []
        dont_know_ids: List[str] = []
        unanswered_ids: List[str] = []
        stored_confidences: Dict[str, ConfidenceLevel] = {}

        # Deduplicate and standardize concepts
        unique_concept_ids = list(dict.fromkeys(all_subject_concept_ids))

        for c_id in unique_concept_ids:
            status = selections.get(c_id, SelfAssessmentStatus.UNANSWERED)
            conf = (confidences or {}).get(c_id, ConfidenceLevel.MEDIUM)
            if isinstance(conf, str):
                try:
                    conf = ConfidenceLevel(conf)
                except ValueError:
                    conf = ConfidenceLevel.MEDIUM
            stored_confidences[c_id] = conf
            assessments[c_id] = ConceptSelfAssessment(
                concept_id=c_id,
                status=status,
                confidence=conf,
            )
            if status == SelfAssessmentStatus.KNOW:
                know_ids.append(c_id)
            elif status == SelfAssessmentStatus.DONT_KNOW:
                dont_know_ids.append(c_id)
            else:
                unanswered_ids.append(c_id)

        session_id = f"init_sess_{uuid.uuid4().hex[:10]}"
        return KnowledgeInitializationSession(
            session_id=session_id,
            learner_id=learner_id,
            subject_id=subject_id,
            self_assessments=assessments,
            know_concept_ids=know_ids,
            dont_know_concept_ids=dont_know_ids,
            unanswered_concept_ids=unanswered_ids,
            confidences=stored_confidences,
            sufficiency_status=KnowledgeSufficiencyStatus.UNINITIALIZED,
        )

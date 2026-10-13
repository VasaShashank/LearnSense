"""
Teacher Service Facade for TAPROOT / LearnSense.
Connects class knowledge states, Teaching Optimizer, and the intervention feedback loop (§10).
"""

import json
import logging
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from phase4.teacher.models import (
    ClassKnowledgeState,
    TeachingInterventionPlan,
    InterventionStatus,
    InterventionOutcome,
)
from phase4.teacher.optimizer import TeachingOptimizer
from backend.services.knowledge_service import KnowledgeService
from backend.services.learner_service import LearnerService
from phase3.learner.models import LearnerState

logger = logging.getLogger(__name__)


def _atomic_write_json(path: Path, data: Any, base_dir: Path) -> Path:
    base_dir.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=str(base_dir), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_name, path)
    except Exception:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise
    return path


class TeacherService:
    """
    Service layer providing class-level collective knowledge tracing,
    instructional recommendations, and intervention loop tracking.
    """

    def __init__(
        self,
        storage_dir: str = "storage/interventions",
        class_storage_dir: str = "storage/classes",
        knowledge_service: Optional[KnowledgeService] = None,
        learner_service: Optional[LearnerService] = None,
    ):
        self.storage_dir = Path(storage_dir)
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        self.class_dir = Path(class_storage_dir)
        self.class_dir.mkdir(parents=True, exist_ok=True)
        self.knowledge_service = knowledge_service or KnowledgeService()
        self.learner_service = learner_service or LearnerService()
        self.optimizer = TeachingOptimizer()

    def register_class(
        self, class_id: str, subject_id: str, class_name: str, enrolled_learner_ids: List[str]
    ) -> Dict[str, Any]:
        """Registers or updates a classroom roster."""
        path = self.class_dir / f"{class_id}.json"
        data = {
            "class_id": class_id,
            "subject_id": subject_id,
            "class_name": class_name,
            "enrolled_learner_ids": enrolled_learner_ids,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        _atomic_write_json(path, data, self.class_dir)
        return data

    def get_class(self, class_id: str) -> Optional[Dict[str, Any]]:
        path = self.class_dir / f"{class_id}.json"
        if not path.exists():
            return None
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)

    def list_classes(self) -> List[Dict[str, Any]]:
        """Lists all registered classroom cohorts, seeding a default if none exists."""
        classes = []
        for p in self.class_dir.glob("*.json"):
            try:
                with open(p, "r", encoding="utf-8") as f:
                    classes.append(json.load(f))
            except Exception as exc:
                logger.warning("Unreadable class %s: %s", p, exc)

        # If only test fixtures or no real subject classes exist, auto-seed one for the active subject
        real_classes = [c for c in classes if not c.get("class_id", "").startswith("cls_integration_test")]
        if not real_classes:
            subjects = self.knowledge_service.list_subjects()
            target_sub_id = subjects[0]["id"] if subjects else "doc_stud-share-sample_c_programs_daa-_lab_programs"
            target_sub_title = subjects[0]["title"] if subjects else "Computer Science & Algorithms"
            default_cls = self.register_class(
                class_id="cls_cohort_alpha_2026",
                subject_id=target_sub_id,
                class_name=f"{target_sub_title} — Cohort 1",
                enrolled_learner_ids=[
                    "student_alex",
                    "student_jordan",
                    "student_sam",
                    "student_taylor",
                    "student_morgan",
                ],
            )
            classes.append(default_cls)

        return sorted(classes, key=lambda c: c.get("class_name", ""))

    def get_class_knowledge_state(
        self, class_id: str, subject_id: Optional[str] = None
    ) -> ClassKnowledgeState:
        """
        Aggregates mastery distributions, prerequisite bottlenecks,
        and misconceptions across all enrolled students in the class.
        """
        class_info = self.get_class(class_id)
        if not class_info:
            # Fallback if class not pre-registered: assume ad-hoc cohort
            learner_ids = []
            subj = subject_id or "default"
        else:
            learner_ids = class_info.get("enrolled_learner_ids", [])
            subj = subject_id or class_info.get("subject_id", "default")

        ctx = self.knowledge_service.get_learning_context(subj)
        all_cids = list(ctx.concepts.keys())

        # Load states for all enrolled learners
        states: List[LearnerState] = []
        for lid in learner_ids:
            st = self.learner_service.get_or_create_learner_state(lid, all_cids)
            states.append(st)

        return self.optimizer.aggregate_class_knowledge_state(
            class_id=class_id,
            subject_id=subj,
            learner_states=states,
            context=ctx,
        )

    def create_intervention_plan(
        self,
        class_id: str,
        subject_id: Optional[str] = None,
        target_concept_id: Optional[str] = None,
        duration_minutes: int = 50,
    ) -> TeachingInterventionPlan:
        """
        Generates an evidence-grounded Teaching Optimizer intervention plan.
        """
        class_info = self.get_class(class_id)
        subj = subject_id or (class_info.get("subject_id") if class_info else None)
        if not subj:
            raise ValueError(f"Subject ID could not be determined for class {class_id}")

        ctx = self.knowledge_service.get_learning_context(subj)
        class_state = self.get_class_knowledge_state(class_id, subject_id=subj)

        plan = self.optimizer.generate_teaching_plan(
            class_state=class_state,
            context=ctx,
            target_concept_id=target_concept_id,
            total_minutes=duration_minutes,
        )

        self.save_intervention_plan(plan)
        return plan

    def save_intervention_plan(self, plan: TeachingInterventionPlan) -> Path:
        path = self.storage_dir / f"{plan.intervention_id}.json"
        data = plan.model_dump(mode="json")
        return _atomic_write_json(path, data, self.storage_dir)

    def load_intervention_plan(self, intervention_id: str) -> Optional[TeachingInterventionPlan]:
        path = self.storage_dir / f"{intervention_id}.json"
        if not path.exists():
            return None
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
            return TeachingInterventionPlan.model_validate(data)

    def approve_intervention_plan(
        self, intervention_id: str, teacher_notes: Optional[str] = None
    ) -> TeachingInterventionPlan:
        """Records teacher review and approval (§10.3)."""
        plan = self.load_intervention_plan(intervention_id)
        if not plan:
            raise ValueError(f"No intervention plan found with id {intervention_id}")

        plan.status = InterventionStatus.APPROVED
        plan.teacher_notes = teacher_notes
        plan.approved_at_iso = datetime.now(timezone.utc).isoformat()
        self.save_intervention_plan(plan)
        return plan

    def evaluate_intervention(
        self, intervention_id: str, target_concept_id: str, pre_state: ClassKnowledgeState
    ) -> InterventionOutcome:
        """Measures educational gain after teacher intervention and reassessment."""
        plan = self.load_intervention_plan(intervention_id)
        if not plan:
            raise ValueError(f"No intervention plan found with id {intervention_id}")

        post_state = self.get_class_knowledge_state(plan.class_id, subject_id=plan.subject_id)
        outcome = self.optimizer.evaluate_intervention_outcome(
            intervention=plan,
            pre_state=pre_state,
            post_state=post_state,
            target_concept_id=target_concept_id,
        )

        plan.status = InterventionStatus.EVALUATED
        self.save_intervention_plan(plan)
        return outcome

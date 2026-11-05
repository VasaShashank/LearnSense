"""Service-layer authorization for class-scoped teacher analytics.

Teacher analytics (``TeacherService``, Person 3 semantics) compute over whatever
class ID they are given. Routes must not be able to reach them without proof that
the caller was authorized for that class. ``ClassStaffGrant`` is that proof: it
can only be minted by ``grant_class_staff_access`` (called after the full
authorization checks in the route layer), and ``AuthorizedTeacherAnalytics``
refuses to run without a valid grant for the requested class.

Internal system operations (batch jobs, tests) may still call ``TeacherService``
directly; this facade is the boundary for *untrusted request* callers.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

from phase3.errors import AuthorizationError

_MINT = object()


@dataclass(frozen=True)
class ClassStaffGrant:
    class_id: str
    org_id: str
    subject_id: str
    user_id: str
    _mint: Any = field(default=None, repr=False, compare=False)


def grant_class_staff_access(course_class: Any, user_id: str) -> ClassStaffGrant:
    """Mint a grant. Call only after institutional authorization succeeded."""
    return ClassStaffGrant(
        class_id=course_class.class_id,
        org_id=course_class.org_id,
        subject_id=course_class.subject_id,
        user_id=user_id,
        _mint=_MINT,
    )


def require_grant(grant: Any, class_id: str) -> ClassStaffGrant:
    if not isinstance(grant, ClassStaffGrant) or grant._mint is not _MINT or grant.class_id != class_id:
        raise AuthorizationError("You do not have permission to perform this operation.")
    return grant


class AuthorizedTeacherAnalytics:
    """The only teacher-analytics entry point used by request handlers."""

    def __init__(self, teacher_service_provider):
        # Provider (not instance) so tests that swap the module-level service still apply.
        self._provider = teacher_service_provider

    @property
    def _svc(self):
        return self._provider()

    def knowledge_state(self, grant: ClassStaffGrant, *, subject_id: Optional[str] = None):
        require_grant(grant, grant.class_id if isinstance(grant, ClassStaffGrant) else "")
        return self._svc.get_class_knowledge_state(grant.class_id, subject_id=subject_id)

    def student_mastery(self, grant: ClassStaffGrant, *, subject_id: Optional[str] = None):
        require_grant(grant, grant.class_id if isinstance(grant, ClassStaffGrant) else "")
        return self._svc.get_class_students_mastery(class_id=grant.class_id, subject_id=subject_id)

    def learning_insights(self, grant: ClassStaffGrant, *, subject_id: Optional[str] = None):
        require_grant(grant, grant.class_id if isinstance(grant, ClassStaffGrant) else "")
        return self._svc.get_student_learning_insights(class_id=grant.class_id, subject_id=subject_id)

    def create_plan(self, grant: ClassStaffGrant, **kwargs):
        require_grant(grant, grant.class_id if isinstance(grant, ClassStaffGrant) else "")
        return self._svc.create_intervention_plan(class_id=grant.class_id, **kwargs)

    def load_plan_for_class(self, grant: ClassStaffGrant, intervention_id: str):
        """The plan, or None if it does not belong to the granted class."""
        require_grant(grant, grant.class_id if isinstance(grant, ClassStaffGrant) else "")
        plan = self._svc.load_intervention_plan(intervention_id)
        return plan if plan is not None and plan.class_id == grant.class_id else None

    def approve_plan(self, grant: ClassStaffGrant, intervention_id: str, teacher_notes: Optional[str]):
        if self.load_plan_for_class(grant, intervention_id) is None:
            raise LookupError(intervention_id)
        return self._svc.approve_intervention_plan(intervention_id=intervention_id, teacher_notes=teacher_notes)

    def evaluate_plan(self, grant: ClassStaffGrant, intervention_id: str, target_concept_id: str):
        if self.load_plan_for_class(grant, intervention_id) is None:
            raise LookupError(intervention_id)
        pre_state = self._svc.get_class_knowledge_state(grant.class_id)
        return self._svc.evaluate_intervention(
            intervention_id=intervention_id, target_concept_id=target_concept_id, pre_state=pre_state
        )

"""
Institutional and B2B Organization Models (§11).
"""

from enum import Enum
from typing import Any, List, Optional
from pydantic import BaseModel, Field, field_validator


class UserRole(str, Enum):
    ADMIN = "ADMIN"
    TEACHER = "TEACHER"
    LEARNER = "LEARNER"


class Organization(BaseModel):
    """An educational institution, university, school, or learning organization."""
    org_id: str
    name: str
    domain: Optional[str] = None
    created_at_iso: str


class OrgMembership(BaseModel):
    """Associates a user with an organization and assigns role permissions."""
    membership_id: str
    org_id: str
    user_id: str
    role: UserRole = UserRole.LEARNER
    is_active: bool = True

    @field_validator("role", mode="before")
    @classmethod
    def normalize_role(cls, v: Any) -> Any:
        if isinstance(v, str):
            v_upper = v.strip().upper()
            if v_upper in UserRole.__members__:
                return UserRole(v_upper)
        return v


class CourseClass(BaseModel):
    """A classroom or cohort within an organization tied to a course/subject."""
    class_id: str
    org_id: str
    subject_id: str
    title: str
    teacher_ids: List[str] = Field(default_factory=list)
    created_at_iso: str


class ClassEnrollment(BaseModel):
    """Enrolls a student in a class. Unenrollment is soft: the row is retained."""
    enrollment_id: str
    class_id: str
    learner_id: str
    enrolled_at_iso: str
    status: str = "active"  # "active" | "unenrolled"

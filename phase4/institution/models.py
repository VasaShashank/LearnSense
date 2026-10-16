"""
Institutional and B2B Organization Models (§11).
"""

from enum import Enum
from typing import List, Optional
from pydantic import BaseModel, Field


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


class CourseClass(BaseModel):
    """A classroom or cohort within an organization tied to a course/subject."""
    class_id: str
    org_id: str
    subject_id: str
    title: str
    teacher_ids: List[str] = Field(default_factory=list)
    created_at_iso: str


class ClassEnrollment(BaseModel):
    """Enrolls a student in a class."""
    enrollment_id: str
    class_id: str
    learner_id: str
    enrolled_at_iso: str

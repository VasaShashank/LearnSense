"""Response models for Person 1-owned endpoints (OpenAPI contract)."""

from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field

from phase4.institution.models import UserRole


class InitializeLearnerResponse(BaseModel):
    learner_id: str
    status: Literal["ready"]
    created: bool
    entry_state: str
    subject_id: Optional[str] = None


class MembershipSummary(BaseModel):
    membership_id: str
    org_id: str
    org_name: str
    role: UserRole
    is_active: bool


class CurrentUserResponse(BaseModel):
    user_id: str = Field(description="Supabase user UUID (canonical identity and learner ID)")
    email: Optional[str] = None
    display_name: Optional[str] = None
    avatar_url: Optional[str] = None
    account_status: Literal["active", "disabled"]
    active_role: Optional[UserRole] = None
    memberships: List[MembershipSummary]


class UpdateProfileRequest(BaseModel):
    display_name: Optional[str] = None
    avatar_url: Optional[str] = None


class UpdateRoleRequest(BaseModel):
    role: str
    org_name: Optional[str] = None


class CreateInvitationRequest(BaseModel):
    email: str
    role: UserRole = UserRole.LEARNER
    class_id: Optional[str] = None


class InvitationResponse(BaseModel):
    invitation_id: str
    org_id: str
    email: str
    role: str
    class_id: Optional[str] = None
    expires_at: str
    token: Optional[str] = None


class IdentityExportResponse(BaseModel):
    user: Optional[Dict[str, Any]]
    memberships: List[Dict[str, Any]]
    enrollments: List[Dict[str, Any]]
    owned_document_ids: List[str]
    audit_events_as_actor: List[Dict[str, Any]]


class OrganizationResponse(BaseModel):
    org_id: str
    name: str
    domain: Optional[str] = None
    created_at_iso: str


class MembershipResponse(BaseModel):
    membership_id: str
    org_id: str
    user_id: str
    role: UserRole
    is_active: bool


class MemberListItem(BaseModel):
    membership_id: str
    user_id: str
    role: UserRole
    is_active: bool


class MembershipPage(BaseModel):
    items: List[MemberListItem]
    total: int
    limit: int
    offset: int


class DeactivationResponse(BaseModel):
    org_id: str
    user_id: str
    role: UserRole
    status: Literal["deactivated", "already_inactive"]


class CourseClassResponse(BaseModel):
    class_id: str
    org_id: str
    subject_id: str
    title: str
    teacher_ids: List[str]
    created_at_iso: str


class EnrollmentResponse(BaseModel):
    enrollment_id: str
    class_id: str
    learner_id: str
    enrolled_at_iso: str
    status: str = "active"


class UnenrollmentResponse(BaseModel):
    class_id: str
    learner_id: str
    status: Literal["unenrolled", "already_unenrolled"]


class TeacherAssignmentRequest(BaseModel):
    teacher_ids: List[str] = Field(default_factory=list, max_length=50)


class RosterResponse(BaseModel):
    class_id: str
    roster: List[str] = Field(description="Active learners only")


class ShareResponse(BaseModel):
    document_id: str
    class_id: str
    status: Literal["shared"]
    created_at: Optional[str] = None


class RevokeShareResponse(BaseModel):
    document_id: str
    class_id: str
    status: Literal["revoked", "not_shared"]

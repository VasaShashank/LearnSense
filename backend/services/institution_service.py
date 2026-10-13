"""
Institution & B2B Service Facade for TAPROOT / LearnSense.
Manages multi-tenant organizations, classes, memberships, and role-based permissions (§11).
"""

import json
import logging
import os
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from phase4.institution.models import (
    Organization,
    OrgMembership,
    CourseClass,
    ClassEnrollment,
    UserRole,
)
from phase3.errors import AuthenticationError, AuthorizationError

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


class InstitutionService:
    """
    Manages organizational boundaries, course rosters, and role-based tenant access.
    """

    def __init__(self, base_dir: str = "storage/institutions"):
        self.base_dir = Path(base_dir)
        self.orgs_dir = self.base_dir / "organizations"
        self.members_dir = self.base_dir / "memberships"
        self.classes_dir = self.base_dir / "classes"
        self.enrollments_dir = self.base_dir / "enrollments"

        for d in [self.orgs_dir, self.members_dir, self.classes_dir, self.enrollments_dir]:
            d.mkdir(parents=True, exist_ok=True)

    # --- Organizations ---

    def create_organization(self, name: str, domain: Optional[str] = None) -> Organization:
        org_id = f"org_{uuid.uuid4().hex[:8]}"
        org = Organization(
            org_id=org_id,
            name=name,
            domain=domain,
            created_at_iso=datetime.now(timezone.utc).isoformat(),
        )
        _atomic_write_json(self.orgs_dir / f"{org_id}.json", org.model_dump(mode="json"), self.orgs_dir)
        return org

    def get_organization(self, org_id: str) -> Optional[Organization]:
        p = self.orgs_dir / f"{org_id}.json"
        if not p.exists():
            return None
        with open(p, "r", encoding="utf-8") as f:
            return Organization.model_validate(json.load(f))

    def list_organizations(self) -> List[Organization]:
        """Lists registered organizations, seeding a default institutional tenant if none exists."""
        orgs = []
        for p in self.orgs_dir.glob("*.json"):
            try:
                with open(p, "r", encoding="utf-8") as f:
                    orgs.append(Organization.model_validate(json.load(f)))
            except Exception as exc:
                logger.warning("Unreadable organization %s: %s", p, exc)

        if not orgs:
            # Seed default institution
            org = self.create_organization(
                name="Apex Institute of Science & Technology",
                domain="apex.edu",
            )
            # Add demo memberships
            self.add_membership(org.org_id, "admin_sterling", UserRole.ADMIN)
            self.add_membership(org.org_id, "prof_vance", UserRole.TEACHER)
            self.add_membership(org.org_id, "student_alex", UserRole.LEARNER)
            self.add_membership(org.org_id, "student_jordan", UserRole.LEARNER)
            self.add_membership(org.org_id, "student_sam", UserRole.LEARNER)
            # Add demo institutional class
            self.create_class(
                org_id=org.org_id,
                subject_id="doc_stud-share-sample_c_programs_daa-_lab_programs",
                title="CS301: Advanced Algorithms & System Paradigms",
                teacher_ids=["prof_vance"],
                creator_user_id="admin_sterling",
            )
            orgs.append(org)

        return sorted(orgs, key=lambda o: o.name)

    # --- Memberships & RBAC ---

    def add_membership(self, org_id: str, user_id: str, role: UserRole) -> OrgMembership:
        mem_id = f"mem_{uuid.uuid4().hex[:8]}"
        mem = OrgMembership(
            membership_id=mem_id,
            org_id=org_id,
            user_id=user_id,
            role=role,
            is_active=True,
        )
        _atomic_write_json(self.members_dir / f"{org_id}_{user_id}.json", mem.model_dump(mode="json"), self.members_dir)
        return mem

    def get_membership(self, org_id: str, user_id: str) -> Optional[OrgMembership]:
        p = self.members_dir / f"{org_id}_{user_id}.json"
        if not p.exists():
            return None
        with open(p, "r", encoding="utf-8") as f:
            return OrgMembership.model_validate(json.load(f))

    def require_role(self, org_id: str, user_id: str, allowed_roles: List[UserRole]) -> OrgMembership:
        mem = self.get_membership(org_id, user_id)
        if not mem or not mem.is_active:
            raise AuthorizationError(
                f"User '{user_id}' has no active membership in organization '{org_id}'",
                details={"org_id": org_id, "user_id": user_id},
            )
        if mem.role not in allowed_roles:
            raise AuthorizationError(
                f"User '{user_id}' with role '{mem.role}' lacks permission for this action",
                details={"required_roles": [r.value for r in allowed_roles], "actual_role": mem.role.value},
            )
        return mem

    # --- Classes & Cohorts ---

    def create_class(
        self,
        org_id: str,
        subject_id: str,
        title: str,
        teacher_ids: List[str],
        creator_user_id: str,
    ) -> CourseClass:
        # Require ADMIN or TEACHER in the organization
        self.require_role(org_id, creator_user_id, [UserRole.ADMIN, UserRole.TEACHER])

        class_id = f"cls_{uuid.uuid4().hex[:8]}"
        c = CourseClass(
            class_id=class_id,
            org_id=org_id,
            subject_id=subject_id,
            title=title,
            teacher_ids=teacher_ids,
            created_at_iso=datetime.now(timezone.utc).isoformat(),
        )
        _atomic_write_json(self.classes_dir / f"{class_id}.json", c.model_dump(mode="json"), self.classes_dir)
        return c

    def get_class(self, class_id: str) -> Optional[CourseClass]:
        p = self.classes_dir / f"{class_id}.json"
        if not p.exists():
            return None
        with open(p, "r", encoding="utf-8") as f:
            return CourseClass.model_validate(json.load(f))

    def list_classes(self, org_id: Optional[str] = None) -> List[CourseClass]:
        classes = []
        for p in self.classes_dir.glob("*.json"):
            try:
                with open(p, "r", encoding="utf-8") as f:
                    c = CourseClass.model_validate(json.load(f))
                    if org_id is None or c.org_id == org_id:
                        classes.append(c)
            except Exception as exc:
                logger.warning("Unreadable class %s: %s", p, exc)
        return sorted(classes, key=lambda c: c.title)

    def enroll_learner(self, class_id: str, learner_id: str, enroller_user_id: str) -> ClassEnrollment:
        c = self.get_class(class_id)
        if not c:
            raise ValueError(f"Class '{class_id}' does not exist")
        # Require teacher or admin of the class's organization
        self.require_role(c.org_id, enroller_user_id, [UserRole.ADMIN, UserRole.TEACHER])

        enr_id = f"enr_{class_id}_{learner_id}"
        enr = ClassEnrollment(
            enrollment_id=enr_id,
            class_id=class_id,
            learner_id=learner_id,
            enrolled_at_iso=datetime.now(timezone.utc).isoformat(),
        )
        _atomic_write_json(self.enrollments_dir / f"{enr_id}.json", enr.model_dump(mode="json"), self.enrollments_dir)
        return enr

    def get_class_roster(self, class_id: str, caller_user_id: str) -> List[str]:
        c = self.get_class(class_id)
        if not c:
            raise ValueError(f"Class '{class_id}' does not exist")
        # Ensure caller is authorized (teacher or admin of the organization)
        self.require_role(c.org_id, caller_user_id, [UserRole.ADMIN, UserRole.TEACHER])

        learners = []
        pattern = f"enr_{class_id}_*.json"
        for p in self.enrollments_dir.glob(pattern):
            try:
                with open(p, "r", encoding="utf-8") as f:
                    enr = json.load(f)
                    learners.append(enr.get("learner_id"))
            except Exception as exc:
                logger.warning("Unreadable enrollment %s: %s", p, exc)
        return sorted(list(set(learners)))

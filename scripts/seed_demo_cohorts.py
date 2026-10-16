"""
Seed Demo Cohorts and Calibrated Student Knowledge States for LearnSense / TAPROOT.
Creates realistic student personas, calibrated Bayesian masteries across key course subjects,
and registers complete, ready-to-demo cohorts for immediate teacher evaluation.
"""

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from phase3.learner.models import LearnerState, ConceptState, MisconceptionRecord, MisconceptionStatusEnum
from phase3.storage.learner_repository import LearnerStateRepository
from phase4.institution.models import CourseClass, ClassEnrollment, OrgMembership, UserRole
from backend.services.knowledge_service import KnowledgeService
from backend.services.teacher_service import TeacherService


DEMO_STUDENTS = [
    {
        "id": "student_alex",
        "name": "Alex Rivera",
        "role": "LEARNER",
        "email": "alex.rivera@apex.edu",
        "profile": "BALANCED",  # Moderate foundations, developing intermediate
    },
    {
        "id": "student_jordan",
        "name": "Jordan Smith",
        "role": "LEARNER",
        "email": "jordan.smith@apex.edu",
        "profile": "ADVANCED",  # High mastery (>80%)
    },
    {
        "id": "student_sam",
        "name": "Sam Taylor",
        "role": "LEARNER",
        "email": "sam.taylor@apex.edu",
        "profile": "STRUGGLING",  # Struggles with recursion & base cases (<35%)
    },
    {
        "id": "student_priya",
        "name": "Priya Sharma",
        "role": "LEARNER",
        "email": "priya.sharma@apex.edu",
        "profile": "ADVANCED",  # High mastery (>85%)
    },
    {
        "id": "student_marcus",
        "name": "Marcus Chen",
        "role": "LEARNER",
        "email": "marcus.chen@apex.edu",
        "profile": "DEVELOPING",  # Medium mastery (45%-65%)
    },
    {
        "id": "student_aisha",
        "name": "Aisha Patel",
        "role": "LEARNER",
        "email": "aisha.patel@apex.edu",
        "profile": "STRUGGLING",  # High attempts, misconception on off-by-one errors
    },
    {
        "id": "student_david",
        "name": "David Kim",
        "role": "LEARNER",
        "email": "david.kim@apex.edu",
        "profile": "BALANCED",  # Moderate foundations
    },
    {
        "id": "student_elena",
        "name": "Elena Rostova",
        "role": "LEARNER",
        "email": "elena.rostova@apex.edu",
        "profile": "TOP_HONORS",  # Mastery > 90%
    },
    {
        "id": "student_carlos",
        "name": "Carlos Mendez",
        "role": "LEARNER",
        "email": "carlos.mendez@apex.edu",
        "profile": "DEVELOPING",
    },
    {
        "id": "student_maya",
        "name": "Maya Lin",
        "role": "LEARNER",
        "email": "maya.lin@apex.edu",
        "profile": "BALANCED",
    },
]


def seed():
    print("[*] Seeding Demo Students, Calibrated Masteries, and Classroom Cohorts...")
    repo = LearnerStateRepository()
    ks = KnowledgeService()
    teacher_svc = TeacherService()

    # Subjects to calibrate
    sub_daa_lab = "doc_stud-share-sample_c_programs_daa-_lab_programs"
    sub_daa_notes = "doc_daa_notes"
    sub_aws = "doc_aws_notes_by_rajesh_aiml"
    sub_cc = "doc_cc_unit1_24_class1"
    sub_lab = "doc_lab_manual"

    ctx_map = {}
    for sub in [sub_daa_lab, sub_daa_notes, sub_aws, sub_cc, sub_lab]:
        try:
            ctx_map[sub] = ks.get_learning_context(sub)
        except Exception as e:
            print(f"Warning: Could not load context for {sub}: {e}")

    # 1. Calibrate Learner States
    for student in DEMO_STUDENTS:
        sid = student["id"]
        profile = student["profile"]
        existing = repo.load_state(sid) or LearnerState(learner_id=sid)

        for sub, ctx in ctx_map.items():
            concepts = list(ctx.concepts.keys())
            total_c = len(concepts)

            for i, cid in enumerate(concepts):
                # Tier based on position in syllabus (foundations first, advanced last)
                tier = i / total_c  # 0.0 to 1.0

                if profile == "TOP_HONORS":
                    mastery = round(0.88 + (0.08 * (1.0 - tier)), 3)
                    attempts = 4
                    correct = 4
                    incorrect = 0
                    rec = [True, True, True, True]
                    unc = 0.25
                elif profile == "ADVANCED":
                    mastery = round(0.78 + (0.15 * (1.0 - tier)), 3)
                    attempts = 4
                    correct = 3
                    incorrect = 1
                    rec = [True, True, False, True]
                    unc = 0.35
                elif profile == "BALANCED":
                    if tier < 0.35:
                        mastery = round(0.68 + (0.10 * (1.0 - tier)), 3)
                        attempts = 3
                        correct = 2
                        incorrect = 1
                        rec = [True, False, True]
                    elif tier < 0.70:
                        mastery = round(0.48 + (0.08 * (1.0 - tier)), 3)
                        attempts = 3
                        correct = 1
                        incorrect = 2
                        rec = [False, True, False]
                    else:
                        mastery = round(0.32 + (0.06 * (1.0 - tier)), 3)
                        attempts = 2
                        correct = 0
                        incorrect = 2
                        rec = [False, False]
                    unc = 0.45
                elif profile == "DEVELOPING":
                    if tier < 0.35:
                        mastery = round(0.60 + (0.10 * (1.0 - tier)), 3)
                        attempts = 3
                        correct = 2
                        incorrect = 1
                        rec = [True, False, True]
                    else:
                        mastery = round(0.38 + (0.08 * (1.0 - tier)), 3)
                        attempts = 2
                        correct = 0
                        incorrect = 2
                        rec = [False, False]
                    unc = 0.50
                elif profile == "STRUGGLING":
                    # Struggling student has friction especially on recursion, divide-and-conquer
                    c_obj = ctx.concepts.get(cid)
                    c_name = (c_obj.canonical_name if c_obj else "").lower()
                    if "recur" in c_name or "time" in c_name or "divide" in c_name or "step" in c_name or "sort" in c_name:
                        mastery = 0.22
                        attempts = 4
                        correct = 0
                        incorrect = 4
                        rec = [False, False, False, False]
                    else:
                        mastery = 0.36
                        attempts = 2
                        correct = 0
                        incorrect = 2
                        rec = [False, False]
                    unc = 0.65
                else:
                    mastery = 0.45
                    attempts = 2
                    correct = 1
                    incorrect = 1
                    rec = [True, False]
                    unc = 0.50

                cs = ConceptState(
                    concept_id=cid,
                    mastery_probability=min(0.98, max(0.15, mastery)),
                    uncertainty=unc,
                    confidence=round(mastery * 0.9, 2),
                    attempt_count=attempts,
                    correct_count=correct,
                    incorrect_count=incorrect,
                    recent_performance=rec,
                    last_attempt=datetime.now(timezone.utc),
                )
                existing.concept_states[cid] = cs

        # Add realistic misconceptions for struggling and developing students
        if profile == "STRUGGLING":
            m_id = f"misc_{sid}_recursion_base"
            existing.misconceptions[m_id] = MisconceptionRecord(
                misconception_id=m_id,
                learner_id=sid,
                concept_id="c_aee41c94ddea",  # Recursive Algorithms
                description="Omits base case check or places it after recursive step, triggering infinite recursion stack overflow.",
                confidence=0.85,
                frequency=3,
                status=MisconceptionStatusEnum.SUPPORTED,
            )
            m_id2 = f"misc_{sid}_off_by_one"
            existing.misconceptions[m_id2] = MisconceptionRecord(
                misconception_id=m_id2,
                learner_id=sid,
                concept_id="c_8d7885b1ece2",  # Time Complexity
                description="Counts loop iterations inclusive instead of exclusive, misjudging quadratic O(n^2) scaling.",
                confidence=0.75,
                frequency=2,
                status=MisconceptionStatusEnum.SUPPORTED,
            )

        repo.save_state(existing)
        print(f"  [OK] Calibrated learner state for {student['name']} ({sid})")

    # 2. Register Institutional Memberships for all demo students
    org_id = "org_373fa56e"  # Apex Institute of Science & Technology
    mem_dir = Path("storage/institutions/memberships")
    mem_dir.mkdir(parents=True, exist_ok=True)
    for student in DEMO_STUDENTS:
        sid = student["id"]
        mem_file = mem_dir / f"{org_id}_{sid}.json"
        mem_data = {
            "membership_id": f"mem_{org_id}_{sid}",
            "org_id": org_id,
            "user_id": sid,
            "role": "learner",
            "created_at_iso": datetime.now(timezone.utc).isoformat(),
        }
        with open(mem_file, "w", encoding="utf-8") as f:
            json.dump(mem_data, f, indent=2)

    # 3. Create Ready-to-Demo Cohorts
    all_student_ids = [s["id"] for s in DEMO_STUDENTS]

    COHORTS_TO_REGISTER = [
        {
            "class_id": "cls_daa_lab_alpha",
            "subject_id": sub_daa_lab,
            "class_name": "CS201: C & DAA Lab — Morning Cohort (Section A)",
            "enrolled": all_student_ids[:8],  # 8 students
        },
        {
            "class_id": "cls_79488767",
            "subject_id": sub_daa_lab,
            "class_name": "CS301: Advanced Algorithms & System Paradigms",
            "enrolled": ["student_alex", "student_jordan", "student_sam", "student_priya", "student_marcus", "student_aisha"],
        },
        {
            "class_id": "cls_daa_theory_sec_b",
            "subject_id": sub_daa_notes,
            "class_name": "CS302: Design & Analysis of Algorithms — Section B",
            "enrolled": ["student_alex", "student_jordan", "student_sam", "student_priya", "student_carlos", "student_maya", "student_david", "student_aisha"],
        },
        {
            "class_id": "cls_cohort_alpha_2026",
            "subject_id": sub_aws,
            "class_name": "CLOUD401: AWS Cloud Architecture — Cohort Alpha",
            "enrolled": ["student_alex", "student_jordan", "student_sam", "student_david", "student_priya", "student_elena"],
        },
        {
            "class_id": "cls_0990edf6",
            "subject_id": sub_aws,
            "class_name": "CLOUD201: Cloud Computing Fundamentals — Section B",
            "enrolled": ["student_sam", "student_aisha", "student_marcus", "student_carlos", "student_david"],
        },
        {
            "class_id": "cls_daa_remediation_beta",
            "subject_id": sub_daa_lab,
            "class_name": "CS201-R: DAA Lab Prerequisite Remediation Cohort",
            "enrolled": ["student_sam", "student_aisha", "student_marcus", "student_carlos"],
        },
        {
            "class_id": "cls_cc_unit1_batch",
            "subject_id": sub_cc,
            "class_name": "CC301: Cloud Computing Architecture — Unit 1 Cohort",
            "enrolled": ["student_alex", "student_jordan", "student_sam", "student_priya", "student_david"],
        },
        {
            "class_id": "cls_systems_lab_honors",
            "subject_id": sub_lab,
            "class_name": "CS501: Advanced Systems Engineering Lab — Honors Section",
            "enrolled": ["student_jordan", "student_priya", "student_elena", "student_alex", "student_david"],
        },
    ]

    classes_dir = Path("storage/classes")
    classes_dir.mkdir(parents=True, exist_ok=True)
    inst_classes_dir = Path("storage/institutions/classes")
    inst_classes_dir.mkdir(parents=True, exist_ok=True)
    enrollments_dir = Path("storage/institutions/enrollments")
    enrollments_dir.mkdir(parents=True, exist_ok=True)

    # Clean legacy test fixture
    test_fixture = classes_dir / "cls_integration_test_101.json"
    if test_fixture.exists():
        try:
            test_fixture.unlink()
        except Exception:
            pass

    for cohort in COHORTS_TO_REGISTER:
        cid = cohort["class_id"]
        sub_id = cohort["subject_id"]
        cname = cohort["class_name"]
        enrolled = cohort["enrolled"]

        # Native class record
        native_record = {
            "class_id": cid,
            "subject_id": sub_id,
            "class_name": cname,
            "enrolled_learner_ids": enrolled,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        with open(classes_dir / f"{cid}.json", "w", encoding="utf-8") as f:
            json.dump(native_record, f, indent=2)

        # Institutional class record
        inst_record = {
            "class_id": cid,
            "org_id": org_id,
            "subject_id": sub_id,
            "title": cname,
            "teacher_ids": ["prof_vance"],
            "created_at_iso": datetime.now(timezone.utc).isoformat(),
        }
        with open(inst_classes_dir / f"{cid}.json", "w", encoding="utf-8") as f:
            json.dump(inst_record, f, indent=2)

        # Enrollments
        for lid in enrolled:
            enr_id = f"enr_{cid}_{lid}"
            enr_record = {
                "enrollment_id": enr_id,
                "class_id": cid,
                "learner_id": lid,
                "enrolled_at_iso": datetime.now(timezone.utc).isoformat(),
            }
            with open(enrollments_dir / f"{enr_id}.json", "w", encoding="utf-8") as f:
                json.dump(enr_record, f, indent=2)

        print(f"  [OK] Cohort Registered: '{cname}' ({cid}) with {len(enrolled)} enrolled learners.")

    print("\n[SUCCESS] Seeding complete! All student cohorts are now ready for demo.")


if __name__ == "__main__":
    seed()

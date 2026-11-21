"""Phase 3 Socratic Teacher Module — Re-export from authoritative Person 3 engine."""

from src.teacher import *
from src.teacher import (
    IndependentTeacherPlanner,
    CohortTeacherManager,
    DynamicTeachingPlan,
    CohortClassroomReport,
    LessonSegment,
)

SocraticTeacher = IndependentTeacherPlanner

"""Phase 3 Assessment Package.

Unifies Person 3's authoritative Expected Information Gain (EIG) Adaptive Assessment Engine,
SymPy Symbolic Solution Verifier, and legacy assessment policies.
"""

from phase3.assessment.models import (
    AssessmentConstraints,
    AssessmentStoppingReason,
    CandidateScore,
)
from phase3.assessment.information_gain import (
    AdaptiveAssessmentPolicy,
    InformationGainPolicy,
    binary_entropy,
)
from phase3.assessment.adaptive_policy import ChapterAssessmentEngine
from phase3.assessment.adaptive_assessment import (
    AdaptiveAssessmentSelector,
    AdaptiveAssessmentSession,
    InformationGainEvaluation,
    AssessmentSelectionResult,
    QuestionItem,
)
from phase3.assessment.solution_verifier import (
    SolutionVerifier,
    SolutionVerificationResult,
    StepVerificationResult,
)

__all__ = [
    "AssessmentConstraints",
    "AssessmentStoppingReason",
    "CandidateScore",
    "AdaptiveAssessmentPolicy",
    "InformationGainPolicy",
    "binary_entropy",
    "ChapterAssessmentEngine",
    "AdaptiveAssessmentSelector",
    "AdaptiveAssessmentSession",
    "InformationGainEvaluation",
    "AssessmentSelectionResult",
    "QuestionItem",
    "SolutionVerifier",
    "SolutionVerificationResult",
    "StepVerificationResult",
]

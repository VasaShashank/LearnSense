"""LearnSense Person 3 — TurboLearn / ChatGPT-Style In-Topic 4-Question Micro-Quiz Engine.

Implements rapid, scaffolded, 4-question formative micro-quizzes for in-topic learning:
1. 4-question micro-quiz generation tied directly to concept knowledge & common misconception traps.
2. Multiple choice options with explicit distractor explanations that clarify the minute differences.
3. Instant per-question feedback (Green: "Correct! <explanation>", Red: "Not quite. <subtle difference note>").
4. On-demand progressive hints (Level 1: Direction clue, Level 2: Equation/method clue).
5. Score tracking (e.g. "Your score: 3/4") and "Try again" session reset.
6. Optional background synchronization to LearnerStateService and MisconceptionTracker.
"""

from __future__ import annotations

import copy
import datetime
import uuid
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple

from src.knowledge_base import GroundedKnowledgeBase, get_default_knowledge_base
from src.misconceptions import MisconceptionTracker
from src.state import LearnerStateService
from src.migration_adapter import (
    CanonicalConceptMigrationAdapter,
    EXCLUDED_FROM_JEE_MAIN_2027,
)
from src.question_bank import (
    QuestionBankAdapter,
    QuestionBankItem,
    get_default_question_bank,
)
from src.curated_questions import (
    CURATED_CONCEPT_QUESTIONS,
    get_concept_meta,
    get_curated_or_generated_questions,
    generate_fallback_questions,
)


@dataclass
class MicroQuizOption:
    """A single multiple choice option with explicit distractor rationale."""
    option_id: str  # 'A', 'B', 'C', 'D'
    text: str
    is_correct: bool
    explanation: str  # Minute difference explanation if chosen

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class MicroQuizItem:
    """A single question in a 4-question micro-quiz."""
    item_id: str
    question_number: int  # 1 to 4
    concept_id: str
    prompt: str
    options: List[MicroQuizOption]
    hints: List[str]  # [Level 1, Level 2]
    distractor_trap_category: Optional[str] = None  # e.g., 'sign_or_direction_error'

    def to_safe_dict(self) -> Dict[str, Any]:
        """Student-facing payload without leaking is_correct or explanations prior to submission."""
        return {
            "item_id": self.item_id,
            "question_number": self.question_number,
            "concept_id": self.concept_id,
            "prompt": self.prompt,
            "options": [{"option_id": opt.option_id, "text": opt.text} for opt in self.options],
            "hint_available": len(self.hints) > 0,
        }

    def to_full_dict(self) -> Dict[str, Any]:
        return {
            "item_id": self.item_id,
            "question_number": self.question_number,
            "concept_id": self.concept_id,
            "prompt": self.prompt,
            "options": [opt.to_dict() for opt in self.options],
            "hints": list(self.hints),
            "distractor_trap_category": self.distractor_trap_category,
        }


@dataclass
class QuestionEvaluationResult:
    """Result of submitting a single answer to a micro-quiz question."""
    item_id: str
    question_number: int
    selected_option_id: str
    is_correct: bool
    feedback_text: str  # e.g. "Correct! ₹10,000 * 8% = ₹800." or "Not quite. ..."
    correct_option_id: str
    minute_difference_explanation: str
    trap_category: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class MicroQuizSession:
    """An interactive 4-question quiz session matching the ChatGPT / TurboLearn format."""
    quiz_id: str
    concept_id: str
    concept_name: str
    learner_id: str
    items: List[MicroQuizItem]
    submitted_answers: Dict[str, str] = field(default_factory=dict)  # item_id -> option_id
    evaluations: Dict[str, QuestionEvaluationResult] = field(default_factory=dict)
    is_completed: bool = False
    score_display: Optional[str] = None  # "3/4"
    total_score: int = 0
    created_at: str = field(default_factory=lambda: datetime.datetime.now(datetime.timezone.utc).isoformat())

    def to_dict(self) -> Dict[str, Any]:
        return {
            "quiz_id": self.quiz_id,
            "concept_id": self.concept_id,
            "concept_name": self.concept_name,
            "learner_id": self.learner_id,
            "items": [item.to_safe_dict() for item in self.items],
            "submitted_answers": copy.deepcopy(self.submitted_answers),
            "evaluations": {k: v.to_dict() for k, v in self.evaluations.items()},
            "is_completed": self.is_completed,
            "score_display": self.score_display,
            "total_score": self.total_score,
            "created_at": self.created_at,
        }


# Curated 4-Question Micro-Quizzes with minute distractor differentiations
CURATED_MICRO_QUIZZES: Dict[str, List[Dict[str, Any]]] = {
    "PHY_KIN": [
        {
            "prompt": "1. A body travels along a semicircle of radius R from point A to point B. What are the distance traveled and displacement magnitude?",
            "options": [
                ("A", "Distance = 2R, Displacement = πR", False, "Not quite. Distance is the actual curved path length (πR), while displacement is the straight-line diameter (2R). You reversed the definitions."),
                ("B", "Distance = πR, Displacement = 2R", True, "Correct! Distance along the semicircle is πR, and displacement between endpoints is the diameter 2R."),
                ("C", "Distance = πR, Displacement = 0", False, "Not quite. Displacement is zero only if the body returns to point A. Here it stops at the opposite end B."),
                ("D", "Distance = 2πR, Displacement = 2R", False, "Not quite. 2πR is the perimeter of a full circle, not a semicircle."),
            ],
            "hints": [
                "Recall: Distance is total path length along the trajectory; displacement is the straight vector from start to finish.",
                "Semicircle perimeter = πR; diameter = 2R.",
            ],
            "trap": "Confusing scalar path length with vector displacement.",
        },
        {
            "prompt": "2. A ball is thrown vertically upward with speed u. At the highest point of its trajectory, which statement is true?",
            "options": [
                ("A", "Both velocity and acceleration are zero", False, "Not quite. Gravity continues to pull the ball downward with acceleration g = 9.8 m/s² even when velocity is momentarily zero."),
                ("B", "Velocity is zero, but acceleration is non-zero directed downward", True, "Correct! At peak height, instantaneous velocity v = 0, but acceleration due to gravity is g downward."),
                ("C", "Velocity is non-zero, but acceleration is zero", False, "Not quite. The ball momentarily stops at the top, so velocity is zero."),
                ("D", "Velocity is directed downward, acceleration is upward", False, "Not quite. Velocity is zero at the apex; acceleration remains downward."),
            ],
            "hints": [
                "Does gravity ever turn off while an object is in free flight?",
                "Use v = u - gt at peak where v = 0.",
            ],
            "trap": "Assuming zero velocity implies zero acceleration.",
        },
        {
            "prompt": "3. The position of a particle is given by x(t) = 3t³ - 2t. Is the equation v = u + at directly applicable to find velocity at any time?",
            "options": [
                ("A", "Yes, because the motion is in one dimension", False, "Not quite. One-dimensional motion does not guarantee constant acceleration. Here acceleration is time-dependent."),
                ("B", "No, because acceleration is time-dependent (a = 18t), requiring calculus", True, "Correct! v = u + at applies ONLY when acceleration is constant. Here a(t) = d²x/dt² = 18t, which varies with time."),
                ("C", "Yes, with a = 3 m/s²", False, "Not quite. The coefficient 3 is part of the cubic position function; acceleration is the second derivative, not a constant."),
                ("D", "No, because velocity cannot be defined for cubic polynomials", False, "Not quite. Velocity is well-defined via calculus v = dx/dt = 9t² - 2."),
            ],
            "hints": [
                "When are the standard kinematic formulas (v = u + at) mathematically valid?",
                "Differentiate position twice: a = d²x/dt².",
            ],
            "trap": "formula_misapplication",
        },
        {
            "prompt": "4. A car accelerates uniformly from rest at 2 m/s² for 5 seconds. What is the total displacement?",
            "options": [
                ("A", "10 m", False, "Not quite. 10 m/s is the final velocity (v = at = 2 * 5), not the displacement."),
                ("B", "50 m", False, "Not quite. 50 m would be the distance if the car moved at 10 m/s for the entire duration without starting from rest."),
                ("C", "25 m", True, "Correct! Using s = ut + 0.5 * a * t² = 0 + 0.5 * 2 * (5)² = 25 m."),
                ("D", "20 m", False, "Not quite. Check your arithmetic: 0.5 * 2 * 25 = 25 m."),
            ],
            "hints": [
                "Which kinematic formula relates displacement to acceleration and time when starting from rest?",
                "Formula: s = ut + (1/2)at² where u = 0.",
            ],
            "trap": "Confusing final speed with total displacement.",
        },
    ],
    "PHY_NLM": [
        {
            "prompt": "1. According to Newton's Third Law, when a horse pulls a cart forward, why does the cart accelerate?",
            "options": [
                ("A", "The horse pulls harder on the cart than the cart pulls back on the horse", False, "Not quite. Action-reaction forces are ALWAYS strictly equal in magnitude and opposite in direction."),
                ("B", "The action and reaction forces act on different bodies, so the net horizontal force on the cart is non-zero", True, "Correct! Action-reaction pairs act on different objects. The cart accelerates because the forward pull on the cart exceeds friction on the cart."),
                ("C", "Action occurs before reaction, creating a momentary net force", False, "Not quite. Action and reaction occur simultaneously without time lag."),
                ("D", "The ground cancels the reaction force on the horse", False, "Not quite. The horse pushes backward on the ground, and the ground pushes forward on the horse."),
            ],
            "hints": [
                "Draw the Free Body Diagram of the cart alone. Which forces act ON the cart?",
                "Action-reaction pairs never act on the same body.",
            ],
            "trap": "inverse_relation_confusion",
        },
        {
            "prompt": "2. An elevator carrying a 60 kg person accelerates upward at 2 m/s². What apparent weight (normal force) does the floor exert? (Take g = 10 m/s²)",
            "options": [
                ("A", "600 N", False, "Not quite. 600 N is the stationary gravitational weight (mg). Accelerating upward increases the normal force."),
                ("B", "480 N", False, "Not quite. 480 N would occur if the elevator were accelerating downward at 2 m/s²."),
                ("C", "720 N", True, "Correct! N - mg = ma => N = m(g + a) = 60 * (10 + 2) = 720 N."),
                ("D", "120 N", False, "Not quite. 120 N is just the net force (ma), not the total normal force (mg + ma)."),
            ],
            "hints": [
                "Set up Newton's second law vertically: F_net = N - mg = ma.",
                "N = m(g + a) for upward acceleration.",
            ],
            "trap": "sign_or_direction_error",
        },
        {
            "prompt": "3. A block rests on a rough horizontal surface with coefficient of static friction μ_s = 0.4. Normal force is 100 N. If a horizontal force of 20 N is applied, what is the friction force?",
            "options": [
                ("A", "40 N", False, "Not quite. 40 N is the MAXIMUM static friction (f_max = μ_s * N). Since 20 N < 40 N, static friction adjusts to match 20 N."),
                ("B", "20 N", True, "Correct! Static friction is a self-adjusting force. It equals the applied force (20 N) up to its maximum threshold of 40 N."),
                ("C", "0 N", False, "Not quite. Without friction, the block would accelerate horizontally."),
                ("D", "80 N", False, "Not quite. Friction cannot exceed the maximum static threshold."),
            ],
            "hints": [
                "Is static friction always equal to μ_s * N, or is that only the limiting maximum?",
                "Static friction self-adjusts to balance applied force until motion impends.",
            ],
            "trap": "Assuming static friction always equals μ_s * N.",
        },
        {
            "prompt": "4. To apply Newton's second law (F = ma) inside an accelerating railway carriage without observing the external world, what must be introduced?",
            "options": [
                ("A", "A higher coefficient of friction", False, "Not quite. Friction is an interfacial contact property, not frame-dependent."),
                ("B", "A fictitious or pseudo force F_pseudo = -m * a_frame opposite to frame acceleration", True, "Correct! In non-inertial accelerating reference frames, pseudo forces must be added: F_pseudo = -m * a_frame."),
                ("C", "Relativistic correction factors", False, "Not quite. At everyday speeds, non-inertial mechanics is handled with classical pseudo forces."),
                ("D", "Nothing; Newton's laws are universally valid in all accelerating frames", False, "Not quite. Newton's laws hold directly only in inertial (non-accelerating) frames."),
            ],
            "hints": [
                "What is required to make non-inertial frames behave like inertial frames?",
                "Think of the apparent force throwing you backward when a car accelerates forward.",
            ],
            "trap": "formula_misapplication",
        },
        {
            "prompt": "5. A ball of mass 0.2 kg moving horizontally at 20 m/s strikes a vertical wall and rebounds elastically at 15 m/s. If the impact duration is 0.01 s, what is the average force exerted on the wall?",
            "options": [
                ("A", "700 N", True, "Correct! J = Δp = m(v_f - v_i) = 0.2 * (15 - (-20)) = 0.2 * 35 = 7.0 N·s. F_avg = J / Δt = 7.0 / 0.01 = 700 N."),
                ("B", "100 N", False, "Not quite. You subtracted speeds without accounting for the reversal of direction (20 - 15 = 5 m/s). Momentum is a vector!"),
                ("C", "350 N", False, "Not quite. Check your division: 7.0 N·s / 0.01 s = 700 N, not 350 N."),
                ("D", "70 N", False, "Not quite. Off by a factor of 10. 7.0 / 0.01 = 700 N."),
            ],
            "hints": [
                "Remember: Impulse J = Δp = m(v_final - v_initial).",
                "Since the ball rebounds in the opposite direction, v_final and v_initial have opposite signs!",
            ],
            "trap": "sign_or_direction_error",
        },
        {
            "prompt": "6. Two masses m1 = 3 kg and m2 = 2 kg are connected by a light inextensible cord over a frictionless pulley (Atwood machine). What is the acceleration of the system? (Take g = 10 m/s²)",
            "options": [
                ("A", "2 m/s²", True, "Correct! a = (m1 - m2)g / (m1 + m2) = (3 - 2)*10 / (3 + 2) = 10 / 5 = 2 m/s²."),
                ("B", "10 m/s²", False, "Not quite. 10 m/s² is free-fall acceleration. The inertia of the lighter mass resists the descent."),
                ("C", "5 m/s²", False, "Not quite. Total mass (3 + 2 = 5 kg) is accelerated by the net gravitational difference (3 - 2)*g = 10 N."),
                ("D", "1 m/s²", False, "Not quite. Check the formula: a = (m1 - m2)g / (m1 + m2)."),
            ],
            "hints": [
                "Write Newton's 2nd law for each mass: m1*g - T = m1*a and T - m2*g = m2*a.",
                "Add the two equations to eliminate tension T: a = (m1 - m2)g / (m1 + m2).",
            ],
            "trap": "formula_misapplication",
        },
        {
            "prompt": "7. Two blocks A (mass 4 kg) and B (mass 2 kg) rest in contact on a frictionless table. A horizontal force F = 18 N pushes on block A toward block B. What is the contact force between A and B?",
            "options": [
                ("A", "6 N", True, "Correct! Common acceleration a = F / (m_A + m_B) = 18 / 6 = 3 m/s². The force required to accelerate B alone is N_AB = m_B * a = 2 * 3 = 6 N."),
                ("B", "18 N", False, "Not quite. 18 N is the total external force accelerating the combined 6 kg system. Block A absorbs 12 N to accelerate itself."),
                ("C", "12 N", False, "Not quite. 12 N is the net force on block A (F - N_AB = 4 * 3 = 12 N), so contact force N_AB = 18 - 12 = 6 N."),
                ("D", "9 N", False, "Not quite. The contact force scales with block B's mass, not an equal split."),
            ],
            "hints": [
                "Find system acceleration first: a = F_total / (m1 + m2).",
                "Isolate block B: what is the ONLY horizontal force acting on B?",
            ],
            "trap": "Assuming the full applied force transmits across the contact interface.",
        },
        {
            "prompt": "8. A car rounds an unbanked circular curve of radius R = 50 m on a flat road. If the coefficient of static friction is μ_s = 0.5, what is the maximum speed the car can have without skidding? (Take g = 10 m/s²)",
            "options": [
                ("A", "15.8 m/s (approx 16 m/s)", True, "Correct! Maximum speed v_max = √(μ_s * g * R) = √(0.5 * 10 * 50) = √250 ≈ 15.81 m/s."),
                ("B", "25 m/s", False, "Not quite. 25 m/s would require μ_s = v²/(gR) = 625 / 500 = 1.25, which exceeds available friction."),
                ("C", "10 m/s", False, "Not quite. √(250) is greater than 10 m/s (10² = 100)."),
                ("D", "5 m/s", False, "Not quite. √(250) ≈ 15.8 m/s."),
            ],
            "hints": [
                "On a flat curve, centripetal force is provided entirely by static friction: f_s = m*v²/R ≤ μ_s*m*g.",
                "Cancel mass m: v_max = √(μ_s * g * R).",
            ],
            "trap": "Neglecting the square root in centripetal force balance.",
        },
    ],
    "CHE_THM": [
        {
            "prompt": "1. For an isolated system undergoing an irreversible spontaneous process, which of the following is strictly true?",
            "options": [
                ("A", "ΔU > 0 and ΔS_system = 0", False, "Not quite. For an isolated system, no energy transfers, so ΔU = 0 by the First Law."),
                ("B", "ΔU = 0 and ΔS_system > 0", True, "Correct! In an isolated system, energy is conserved (ΔU = 0) and entropy strictly increases (ΔS > 0) for irreversible spontaneous changes."),
                ("C", "ΔU < 0 and ΔS_system > 0", False, "Not quite. An isolated system cannot exchange heat or work, so internal energy cannot decrease."),
                ("D", "ΔH = 0 and ΔS_system < 0", False, "Not quite. Entropy never decreases spontaneously in an isolated system."),
            ],
            "hints": [
                "What does 'isolated system' mean regarding energy exchange?",
                "First Law gives ΔU = q + w = 0; Second Law gives ΔS_isolated > 0.",
            ],
            "trap": "Confusing closed systems with isolated systems.",
        },
        {
            "prompt": "2. In an isothermal reversible expansion of an ideal gas, how are heat absorbed (q) and work done (w) related?",
            "options": [
                ("A", "q = 0 and w > 0", False, "Not quite. q = 0 is an adiabatic process, not an isothermal process."),
                ("B", "q = -w = nRT ln(V2/V1)", True, "Correct! For an isothermal process of an ideal gas, ΔU = 0. Therefore q = -w = nRT ln(V2/V1)."),
                ("C", "q = w and ΔU = 2q", False, "Not quite. By the First Law ΔU = q + w. Since ΔU = 0 for isothermal ideal gas, q = -w."),
                ("D", "w = 0 and q = nC_v ΔT", False, "Not quite. Gas expands against a boundary, so work is non-zero."),
            ],
            "hints": [
                "For an ideal gas, internal energy depends only on temperature: U = f(T).",
                "If T is constant, what is ΔU? Then apply ΔU = q + w.",
            ],
            "trap": "Confusing adiabatic (q=0) with isothermal (ΔT=0).",
        },
        {
            "prompt": "3. A chemical reaction has ΔH > 0 (endothermic) and ΔS > 0. At what temperatures is the reaction spontaneous at standard pressure?",
            "options": [
                ("A", "At all temperatures", False, "Not quite. When T is low, ΔH dominates, making ΔG = ΔH - TΔS > 0 (non-spontaneous)."),
                ("B", "At low temperatures only", False, "Not quite. Low temperature favors the unfavorable endothermic ΔH term."),
                ("C", "At high temperatures where T > ΔH / ΔS", True, "Correct! For spontaneity, ΔG = ΔH - TΔS < 0, which requires TΔS > ΔH, or T > ΔH / ΔS."),
                ("D", "Never spontaneous at any temperature", False, "Not quite. High temperatures make -TΔS sufficiently negative to overcome positive ΔH."),
            ],
            "hints": [
                "Gibbs-Helmholtz equation: ΔG = ΔH - TΔS.",
                "Spontaneous when ΔG < 0.",
            ],
            "trap": "sign_or_direction_error",
        },
        {
            "prompt": "4. Which of the following is an intensive thermodynamic property?",
            "options": [
                ("A", "Enthalpy (H)", False, "Not quite. Enthalpy scales directly with the amount of substance (extensive)."),
                ("B", "Molar Heat Capacity (C_m)", True, "Correct! Molar heat capacity is normalized per mole, making it independent of total system size (intensive)."),
                ("C", "Entropy (S)", False, "Not quite. Entropy depends on system size and mass (extensive)."),
                ("D", "Internal Energy (U)", False, "Not quite. Total internal energy scales with the mass of the sample."),
            ],
            "hints": [
                "Intensive properties do not depend on the quantity or mass of matter present.",
                "Dividing an extensive property by moles or mass yields an intensive property.",
            ],
            "trap": "Confusing extensive heat capacity with intensive molar heat capacity.",
        },
    ],
}


# Populate canonical ID aliases and import rich curated questions
CURATED_MICRO_QUIZZES["cc_3e003bf9b038a36b"] = CURATED_MICRO_QUIZZES["PHY_KIN"]
CURATED_MICRO_QUIZZES["cc_e070c64d30e5e623"] = CURATED_MICRO_QUIZZES["PHY_NLM"]
CURATED_MICRO_QUIZZES["cc_f18f919f23ce794d"] = CURATED_MICRO_QUIZZES["CHE_THM"]

# Incorporate comprehensive curated JEE Main question bank
CURATED_MICRO_QUIZZES.update(CURATED_CONCEPT_QUESTIONS)
CURATED_MICRO_QUIZZES["PHY_MAG"] = CURATED_CONCEPT_QUESTIONS.get("cc_0a599e2579d7239e", [])
CURATED_MICRO_QUIZZES["PHY_ELC"] = CURATED_CONCEPT_QUESTIONS.get("cc_0dc99667b34c7291", [])
CURATED_MICRO_QUIZZES["PHY_WPE"] = CURATED_CONCEPT_QUESTIONS.get("cc_5f9917b8333fae45", [])
CURATED_MICRO_QUIZZES["PHY_ROT"] = CURATED_CONCEPT_QUESTIONS.get("cc_f9b37ebf7ac48dce", [])
CURATED_MICRO_QUIZZES["CHE_BND"] = CURATED_CONCEPT_QUESTIONS.get("cc_f11cab60cdf232c0", [])
CURATED_MICRO_QUIZZES["MAT_DIF"] = CURATED_CONCEPT_QUESTIONS.get("cc_c31f5c19a669612c", [])
CURATED_MICRO_QUIZZES["MAT_INT"] = CURATED_CONCEPT_QUESTIONS.get("cc_7cead0c2605b359f", [])
CURATED_MICRO_QUIZZES["MAT_PNC"] = CURATED_CONCEPT_QUESTIONS.get("cc_6c289cbb2834295f", [])


_GLOBAL_ACTIVE_QUIZ_SESSIONS: Dict[str, MicroQuizSession] = {}


class MicroQuizEngine:
    """Manages generation, real-time evaluation, and score tallying for 4-question micro-quizzes."""

    def __init__(
        self,
        knowledge_base: Optional[GroundedKnowledgeBase] = None,
        misconception_tracker: Optional[MisconceptionTracker] = None,
        question_bank: Optional[QuestionBankAdapter] = None,
        migration_adapter: Optional[CanonicalConceptMigrationAdapter] = None,
        sessions: Optional[Dict[str, MicroQuizSession]] = None,
    ) -> None:
        self.knowledge_base = knowledge_base or get_default_knowledge_base()
        self.misconception_tracker = misconception_tracker
        self.question_bank = question_bank or get_default_question_bank()
        self.migration_adapter = migration_adapter or CanonicalConceptMigrationAdapter()
        self._active_sessions = sessions if sessions is not None else _GLOBAL_ACTIVE_QUIZ_SESSIONS

    def _synthesize_quiz_items_from_bank(
        self,
        questions: List[QuestionBankItem],
        concept_id: str,
        quiz_id: str,
    ) -> List[MicroQuizItem]:
        """Converts question bank items into interactive MicroQuizItems with scaffolding."""
        items: List[MicroQuizItem] = []
        meta = get_concept_meta(concept_id)
        c_content = self.knowledge_base.get_concept_content(concept_id)
        concept_title = c_content.concept_name if c_content else meta.get("concept_name", "Core Concept")

        has_real_questions = any(bool(q.prompt and q.options) for q in questions)
        if not has_real_questions:
            raw_fallback = generate_fallback_questions(concept_id)
            for i, q in enumerate(raw_fallback[:4]):
                opts = [
                    MicroQuizOption(
                        option_id=opt_id,
                        text=opt_text,
                        is_correct=is_corr,
                        explanation=expl,
                    )
                    for opt_id, opt_text, is_corr, expl in q["options"]
                ]
                items.append(
                    MicroQuizItem(
                        item_id=f"{quiz_id}_Q{i+1}",
                        question_number=i + 1,
                        concept_id=concept_id,
                        prompt=q["prompt"],
                        options=opts,
                        hints=q.get("hints", []),
                        distractor_trap_category=q.get("trap"),
                    )
                )
            return items

        for i, q in enumerate(questions[:4]):
            q_num = i + 1
            if q.prompt and q.options:
                prompt_text = f"{q_num}. {q.prompt}"
                opts = [
                    MicroQuizOption(
                        option_id=opt.option_id,
                        text=opt.text,
                        is_correct=opt.is_correct,
                        explanation=opt.explanation or ("Correct!" if opt.is_correct else "Incorrect."),
                    )
                    for opt in q.options
                ]
                hints = list(q.hints) if q.hints else [f"Review foundational principles of {concept_title}."]
                trap = q.metadata.get("trap", "conceptual_misconception")
            else:
                prompt_text = f"{q_num}. In {concept_title}, which statement accurately describes the core physical principle?"
                opts = [
                    MicroQuizOption(
                        option_id="A",
                        text=f"The principle holds under verified boundary conditions in {concept_title}.",
                        is_correct=True,
                        explanation=f"Correct! Conservative constraints and valid boundaries define {concept_title}.",
                    ),
                    MicroQuizOption(
                        option_id="B",
                        text=f"The system violates thermodynamic and energy conservation.",
                        is_correct=False,
                        explanation=f"Not quite. Fundamental conservation laws are strictly preserved in {concept_title}.",
                    ),
                    MicroQuizOption(
                        option_id="C",
                        text=f"The quantity exhibits arbitrary scaling independent of input parameters.",
                        is_correct=False,
                        explanation=f"Not quite. Physical quantities scale strictly according to governing equations in {concept_title}.",
                    ),
                    MicroQuizOption(
                        option_id="D",
                        text=f"The principle holds universally irrespective of physical boundary constraints.",
                        is_correct=False,
                        explanation=f"Not quite. Over-generalizing without checking boundary conditions is a common trap.",
                    ),
                ]
                hints = [
                    f"Consider the governing physical assumptions of {concept_title}.",
                    "Check whether conservation laws restrict unconstrained scaling.",
                ]
                trap = "overgeneralization_or_boundary_omission"

            items.append(
                MicroQuizItem(
                    item_id=f"{quiz_id}_Q{q_num}",
                    question_number=q_num,
                    concept_id=concept_id,
                    prompt=prompt_text,
                    options=opts,
                    hints=hints,
                    distractor_trap_category=trap,
                )
            )
        return items

    def generate_quiz(
        self,
        learner_id: str,
        concept_id: str,
        difficulty: Optional[str] = None,
        question_type: Optional[str] = None,
        jee_main_2027_only: bool = True,
    ) -> MicroQuizSession:
        """Generates a 4-question micro-quiz for the target concept without silent fallback."""
        raw_cid = str(concept_id).strip()
        if not raw_cid:
            raise ValueError("concept_id cannot be empty.")

        quiz_id = f"QUIZ_{uuid.uuid4().hex[:10].upper()}"

        try:
            canonical_cid = self.migration_adapter.to_canonical_id(raw_cid, default_split_to_ray=True)
        except Exception:
            canonical_cid = raw_cid

        # Syllabus eligibility check
        if jee_main_2027_only and canonical_cid in EXCLUDED_FROM_JEE_MAIN_2027:
            raise ValueError(
                f"no_questions_available: Concept '{raw_cid}' ({canonical_cid}) is excluded from JEE Main 2027 syllabus."
            )

        # 1. Check curated micro-quizzes first
        raw_items = CURATED_MICRO_QUIZZES.get(raw_cid) or CURATED_MICRO_QUIZZES.get(canonical_cid)
        if not raw_items:
            raw_items = get_curated_or_generated_questions(canonical_cid)

        items: List[MicroQuizItem] = []

        if raw_items:
            for i, q in enumerate(raw_items[:4]):
                opts: List[MicroQuizOption] = []
                for opt_id, opt_text, is_corr, expl in q["options"]:
                    opts.append(
                        MicroQuizOption(
                            option_id=opt_id,
                            text=opt_text,
                            is_correct=is_corr,
                            explanation=expl,
                        )
                    )
                items.append(
                    MicroQuizItem(
                        item_id=f"{quiz_id}_Q{i+1}",
                        question_number=i + 1,
                        concept_id=canonical_cid,
                        prompt=q["prompt"],
                        options=opts,
                        hints=q.get("hints", []),
                        distractor_trap_category=q.get("trap"),
                    )
                )
        else:
            # 2. Query QuestionBankAdapter for canonical concept items
            bank_questions = self.question_bank.get_questions_for_concept(
                concept_id=canonical_cid,
                difficulty=difficulty,
                question_type=question_type,
                jee_main_2027_only=jee_main_2027_only,
                limit=4,
            )
            if not bank_questions:
                raise ValueError(
                    f"no_questions_available for concept '{raw_cid}' (canonical: '{canonical_cid}')."
                )
            items = self._synthesize_quiz_items_from_bank(bank_questions, canonical_cid, quiz_id)

        meta = get_concept_meta(canonical_cid)
        c_content = self.knowledge_base.get_concept_content(canonical_cid)
        c_name = c_content.concept_name if c_content else meta.get("concept_name", canonical_cid)

        session = MicroQuizSession(
            quiz_id=quiz_id,
            concept_id=canonical_cid,
            concept_name=c_name,
            learner_id=learner_id,
            items=items,
        )
        self._active_sessions[quiz_id] = session
        return session

    def get_session(self, quiz_id: str) -> Optional[MicroQuizSession]:
        return self._active_sessions.get(quiz_id)

    def evaluate_single_answer(
        self,
        quiz_id: str,
        item_id: str,
        selected_option_id: str,
        state_service: Optional[LearnerStateService] = None,
    ) -> QuestionEvaluationResult:
        """Evaluates a single option immediately, generating the TurboLearn/ChatGPT style feedback."""
        session = self._active_sessions.get(quiz_id)
        if not session:
            raise KeyError(f"Quiz session '{quiz_id}' not found.")

        target_item = next((it for it in session.items if it.item_id == item_id), None)
        if not target_item:
            raise KeyError(f"Item '{item_id}' not found in quiz session '{quiz_id}'.")

        selected_opt = next((o for o in target_item.options if o.option_id == selected_option_id.upper()), None)
        correct_opt = next((o for o in target_item.options if o.is_correct), target_item.options[0])

        if not selected_opt:
            raise ValueError(f"Invalid option ID '{selected_option_id}'.")

        is_corr = selected_opt.is_correct
        feedback_prefix = "Correct!" if is_corr else "Not quite."
        feedback_text = f"{feedback_prefix} {selected_opt.explanation}"

        res = QuestionEvaluationResult(
            item_id=item_id,
            question_number=target_item.question_number,
            selected_option_id=selected_opt.option_id,
            is_correct=is_corr,
            feedback_text=feedback_text,
            correct_option_id=correct_opt.option_id,
            minute_difference_explanation=selected_opt.explanation,
            trap_category=target_item.distractor_trap_category if not is_corr else None,
        )

        session.submitted_answers[item_id] = selected_opt.option_id
        session.evaluations[item_id] = res

        # Check if all 4 are answered
        if len(session.submitted_answers) == len(session.items):
            score = sum(1 for ev in session.evaluations.values() if ev.is_correct)
            session.total_score = score
            session.score_display = f"{score}/{len(session.items)}"
            session.is_completed = True

        # Optional state update
        if state_service:
            state_service.process_attempt(
                learner_id=session.learner_id,
                concept_id=target_item.concept_id,
                attempt_id=f"MQ_ATT_{uuid.uuid4().hex[:8]}",
                is_correct=is_corr,
            )

        return res

    def get_hint(
        self,
        quiz_id: str,
        item_id: str,
        hint_level: int = 1,
    ) -> Dict[str, Any]:
        """Returns progressive hint without revealing the answer."""
        session = self._active_sessions.get(quiz_id)
        if not session:
            raise KeyError(f"Quiz session '{quiz_id}' not found.")

        target_item = next((it for it in session.items if it.item_id == item_id), None)
        if not target_item:
            raise KeyError(f"Item '{item_id}' not found in quiz session '{quiz_id}'.")

        hints = target_item.hints
        if not hints:
            return {"hint_level": hint_level, "hint_text": "Review the governing definition for this concept."}

        idx = max(0, min(len(hints) - 1, hint_level - 1))
        return {
            "item_id": item_id,
            "hint_level": idx + 1,
            "hint_text": hints[idx],
        }

    def reset_quiz(self, quiz_id: str) -> MicroQuizSession:
        """Resets the session for a clean 'Try again' retry."""
        session = self._active_sessions.get(quiz_id)
        if not session:
            raise KeyError(f"Quiz session '{quiz_id}' not found.")

        session.submitted_answers.clear()
        session.evaluations.clear()
        session.is_completed = False
        session.total_score = 0
        session.score_display = None
        return session

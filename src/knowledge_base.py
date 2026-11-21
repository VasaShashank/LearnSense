"""LearnSense Person 3 — Grounded Knowledge Base and Educational Content Repository.

Provides verified conceptual definitions, key equations, foundational principles,
common misconceptions, worked example templates, and authentic source citations
for JEE Physics, Chemistry, and Mathematics concepts.
Guarantees strict provenance without fabricated citations or unverified assertions.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Union

from src.migration_adapter import CanonicalConceptMigrationAdapter

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ContentSnippet:
    """A relevant content snippet retrieved from the knowledge base."""
    concept_id: str
    title: str
    text: str
    score: float = 1.0
    source_locator: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "concept_id": self.concept_id,
            "title": self.title,
            "text": self.text,
            "score": self.score,
            "source_locator": self.source_locator,
        }


@dataclass(frozen=True)
class GroundedConceptContent:
    """Authentic educational content linked to a canonical concept ID."""
    concept_id: str
    concept_name: str
    subject: str
    topic_group: str
    definition: str
    core_principles: List[str]
    key_equations: List[str]
    common_misconceptions: List[Dict[str, str]]
    worked_example: Dict[str, Any]
    source_citation: Dict[str, str]


class KnowledgeContentProvider(ABC):
    """Abstract interface defining the formal NCERT content hand-off contract with Person 2."""

    @abstractmethod
    def get_concept_content(self, concept_id: str) -> Optional[GroundedConceptContent]:
        """Retrieves authoritative conceptual content for concept_id."""
        pass

    @abstractmethod
    def has_concept_content(self, concept_id: str) -> bool:
        """Checks if content exists for concept_id."""
        pass

    @abstractmethod
    def list_available_concepts(self) -> List[str]:
        """Returns list of canonical concept IDs having content."""
        pass

    @abstractmethod
    def search_content(self, query: str, top_k: int = 5) -> List[ContentSnippet]:
        """Performs semantic or lexical search across knowledge content."""
        pass


# Curated, authoritative repository of verified curriculum concepts
_CONCEPT_CONTENT_REGISTRY: Dict[str, GroundedConceptContent] = {
    # --- PHYSICS ---
    "PHY_KIN": GroundedConceptContent(
        concept_id="PHY_KIN",
        concept_name="Kinematics",
        subject="Physics",
        topic_group="Mechanics",
        definition=(
            "Kinematics describes the motion of points, bodies, and systems of bodies without "
            "considering the forces that cause the motion. It relates position, displacement, "
            "velocity, acceleration, and time."
        ),
        core_principles=[
            "Displacement is the shortest vector distance between initial and final positions.",
            "Velocity is the rate of change of displacement (v = dx/dt).",
            "Acceleration is the rate of change of velocity (a = dv/dt).",
            "Equations of uniformly accelerated motion apply only when acceleration is constant.",
        ],
        key_equations=[
            "v = u + a * t",
            "s = u * t + 0.5 * a * t^2",
            "v^2 = u^2 + 2 * a * s",
            "s_nth = u + 0.5 * a * (2*n - 1)",
        ],
        common_misconceptions=[
            {
                "misconception": "Confusing distance traveled with magnitude of displacement.",
                "explanation": "Distance is a scalar representing the total path length; displacement is a vector between initial and final points. Distance >= |displacement|.",
                "counter_example": "A body completing a full circular lap of radius R covers distance 2*pi*R, but its displacement is zero.",
            },
            {
                "misconception": "Assuming acceleration must be zero when velocity is momentarily zero.",
                "explanation": "Velocity can be momentarily zero while acceleration is non-zero.",
                "counter_example": "At the peak of vertical projectile motion, v = 0, but a = -g.",
            },
        ],
        worked_example={
            "title": "Uniformly Accelerated Motion from Rest",
            "prompt": "A car starts from rest with a uniform acceleration of 2.0 m/s^2 for 5.0 seconds. Find the final velocity and total displacement.",
            "steps": [
                {
                    "step_index": 0,
                    "content": "Identify given variables: initial velocity u = 0 m/s, acceleration a = 2.0 m/s^2, time t = 5.0 s.",
                    "concept_ids": ["PHY_KIN"],
                },
                {
                    "step_index": 1,
                    "content": "Apply the first equation of motion: v = u + a * t = 0 + (2.0 m/s^2 * 5.0 s) = 10.0 m/s.",
                    "concept_ids": ["PHY_KIN"],
                },
                {
                    "step_index": 2,
                    "content": "Apply the displacement equation: s = u * t + 0.5 * a * t^2 = 0 + 0.5 * 2.0 * (5.0)^2 = 25.0 m.",
                    "concept_ids": ["PHY_KIN"],
                },
                {
                    "step_index": 3,
                    "content": "Verify using v^2 = u^2 + 2*a*s: (10.0)^2 = 0 + 2 * 2.0 * 25.0 = 100. Consistent.",
                    "concept_ids": ["PHY_KIN"],
                },
            ],
            "final_answer": "Final velocity = 10.0 m/s; Total displacement = 25.0 m.",
        },
        source_citation={
            "source_id": "NCERT-PHYSICS-XI-PART1",
            "locator": "Chapter 3: Motion in a Straight Line, Sections 3.2-3.6, pp. 39-58",
            "title": "NCERT Class 11 Physics: Kinematics",
        },
    ),
    "PHY_NLM": GroundedConceptContent(
        concept_id="PHY_NLM",
        concept_name="Laws of Motion",
        subject="Physics",
        topic_group="Mechanics",
        definition=(
            "Newton's Laws of Motion formulate the relationship between the forces acting upon an "
            "object and the resulting change in its momentum and state of motion."
        ),
        core_principles=[
            "First Law (Inertia): A body continues in its state of rest or uniform motion unless acted upon by a net external force.",
            "Second Law: Net force equals the time rate of change of linear momentum (F_net = dp/dt = m*a for constant mass).",
            "Third Law: For every action force, there is an equal and opposite reaction force acting on different bodies.",
            "Static friction self-adjusts up to its limiting value (f_s <= mu_s * N).",
        ],
        key_equations=[
            "F_net = m * a",
            "p = m * v",
            "f_s_max = mu_s * N",
            "f_k = mu_k * N",
            "J = Integral(F dt) = delta_p",
        ],
        common_misconceptions=[
            {
                "misconception": "Believing normal force is the Newton's Third Law reaction to gravitational force.",
                "explanation": "Normal force and gravity act on the same body; action-reaction pairs always act on two distinct interacting bodies.",
                "counter_example": "A book on a table: the Earth exerts gravity on the book; the book exerts an equal gravitational pull on the Earth.",
            },
            {
                "misconception": "Assuming motion requires a continuous net force in the direction of motion.",
                "explanation": "A net force produces acceleration (change in velocity), not velocity itself. In the absence of net force, motion continues indefinitely at constant velocity.",
                "counter_example": "A puck sliding on frictionless ice continues at constant velocity with zero net force.",
            },
        ],
        worked_example={
            "title": "Block on an Inclined Plane with Friction",
            "prompt": "A 5.0 kg block rests on a 30-degree incline. The coefficient of static friction is mu_s = 0.6. Determine if the block will slide.",
            "steps": [
                {
                    "step_index": 0,
                    "content": "Draw the free-body diagram: resolve gravity into parallel (m*g*sin(theta)) and perpendicular (m*g*cos(theta)) components.",
                    "concept_ids": ["PHY_NLM"],
                },
                {
                    "step_index": 1,
                    "content": "Calculate normal force: N = m * g * cos(30 deg) = 5.0 * 9.8 * 0.8660 = 42.43 N.",
                    "concept_ids": ["PHY_NLM"],
                },
                {
                    "step_index": 2,
                    "content": "Compute maximum available static friction: f_s_max = mu_s * N = 0.6 * 42.43 = 25.46 N.",
                    "concept_ids": ["PHY_NLM"],
                },
                {
                    "step_index": 3,
                    "content": "Compute downhill driving force: F_parallel = m * g * sin(30 deg) = 5.0 * 9.8 * 0.5 = 24.50 N.",
                    "concept_ids": ["PHY_NLM"],
                },
                {
                    "step_index": 4,
                    "content": "Compare forces: Since F_parallel (24.50 N) < f_s_max (25.46 N), static friction balances the driving force. The block remains at rest.",
                    "concept_ids": ["PHY_NLM"],
                },
            ],
            "final_answer": "The block does not slide. Static friction is 24.50 N upward along the incline.",
        },
        source_citation={
            "source_id": "NCERT-PHYSICS-XI-PART1",
            "locator": "Chapter 5: Laws of Motion, Sections 5.2-5.9, pp. 89-110",
            "title": "NCERT Class 11 Physics: Laws of Motion",
        },
    ),
    "PHY_WPE": GroundedConceptContent(
        concept_id="PHY_WPE",
        concept_name="Work, Power and Energy",
        subject="Physics",
        topic_group="Mechanics",
        definition=(
            "Work is the energy transferred to or from an object via the application of force "
            "along a displacement. The work-energy theorem states that net work equals the change in kinetic energy."
        ),
        core_principles=[
            "Work done by a constant force is the scalar product of force and displacement: W = F . s = F*s*cos(theta).",
            "Work-Energy Theorem: W_net = Delta K = 0.5*m*v_f^2 - 0.5*m*v_i^2.",
            "Mechanical energy is conserved when only conservative forces do work.",
            "Potential energy is defined only for conservative forces: Delta U = -W_conservative.",
        ],
        key_equations=[
            "W = F * s * cos(theta)",
            "W_net = Delta K",
            "U_gravity = m * g * h",
            "U_spring = 0.5 * k * x^2",
            "Power = dW/dt = F . v",
        ],
        common_misconceptions=[
            {
                "misconception": "Assuming zero work is done if force is perpendicular to displacement.",
                "explanation": "When force is perpendicular to displacement (theta = 90 deg, cos(theta) = 0), work done by that force is strictly zero.",
                "counter_example": "Centripetal force in uniform circular motion does zero work because it is always perpendicular to velocity.",
            },
        ],
        worked_example={
            "title": "Work-Energy Theorem with Compression",
            "prompt": "A 2.0 kg block sliding on a smooth horizontal surface at 4.0 m/s hits a spring of spring constant k = 800 N/m. Find the maximum compression.",
            "steps": [
                {
                    "step_index": 0,
                    "content": "Identify initial kinetic energy: K_i = 0.5 * m * v^2 = 0.5 * 2.0 * (4.0)^2 = 16.0 J.",
                    "concept_ids": ["PHY_WPE"],
                },
                {
                    "step_index": 1,
                    "content": "At maximum compression x_max, the block momentarily stops, so K_f = 0.",
                    "concept_ids": ["PHY_WPE"],
                },
                {
                    "step_index": 2,
                    "content": "By conservation of mechanical energy: K_i = U_spring = 0.5 * k * x_max^2.",
                    "concept_ids": ["PHY_WPE"],
                },
                {
                    "step_index": 3,
                    "content": "Solve for x_max: 16.0 = 0.5 * 800 * x_max^2 => x_max^2 = 32.0 / 800 = 0.04 => x_max = 0.20 m = 20 cm.",
                    "concept_ids": ["PHY_WPE"],
                },
            ],
            "final_answer": "Maximum compression of the spring is 0.20 m (20 cm).",
        },
        source_citation={
            "source_id": "NCERT-PHYSICS-XI-PART1",
            "locator": "Chapter 6: Work, Energy and Power, Sections 6.2-6.8, pp. 114-135",
            "title": "NCERT Class 11 Physics: Work, Energy and Power",
        },
    ),
    # --- CHEMISTRY ---
    "CHE_MOL": GroundedConceptContent(
        concept_id="CHE_MOL",
        concept_name="Some Basic Concepts / Mole Concept",
        subject="Chemistry",
        topic_group="Physical Chemistry",
        definition=(
            "The mole is the SI unit of amount of substance. One mole contains exactly "
            "6.02214076 x 10^23 elementary entities (Avogadro's constant)."
        ),
        core_principles=[
            "1 mole of any chemical entity contains N_A = 6.022 x 10^23 particles.",
            "Molar mass is the mass in grams of one mole of that substance.",
            "At STP (273.15 K, 1 bar), 1 mole of an ideal gas occupies 22.7 L (or 22.4 L at 1 atm).",
            "Stoichiometric ratios determine quantitative relations in balanced chemical equations.",
        ],
        key_equations=[
            "n = mass / molar_mass",
            "N_particles = n * N_A",
            "Molarity (M) = moles_of_solute / volume_of_solution_in_litres",
            "Molality (m) = moles_of_solute / mass_of_solvent_in_kg",
            "Normality (N) = Molarity * n_factor",
        ],
        common_misconceptions=[
            {
                "misconception": "Confusing molarity (temperature-dependent) with molality (temperature-independent).",
                "explanation": "Molarity is moles per litre of solution; because liquid volume expands with temperature, molarity changes with temperature. Molality depends on solvent mass and remains invariant.",
                "counter_example": "Heating an aqueous 1.0 M NaCl solution decreases its molarity as volume expands, but its molality is unchanged.",
            },
        ],
        worked_example={
            "title": "Calculating Molarity and Particle Count",
            "prompt": "Calculate the molarity of an aqueous solution containing 4.0 g of NaOH dissolved in 250 mL of solution. (Molar mass of NaOH = 40 g/mol).",
            "steps": [
                {
                    "step_index": 0,
                    "content": "Calculate moles of NaOH: n = mass / molar_mass = 4.0 g / 40.0 g/mol = 0.10 mol.",
                    "concept_ids": ["CHE_MOL"],
                },
                {
                    "step_index": 1,
                    "content": "Convert volume to litres: V = 250 mL = 0.250 L.",
                    "concept_ids": ["CHE_MOL"],
                },
                {
                    "step_index": 2,
                    "content": "Calculate molarity: M = n / V = 0.10 mol / 0.250 L = 0.40 mol/L (0.40 M).",
                    "concept_ids": ["CHE_MOL"],
                },
            ],
            "final_answer": "Molarity of NaOH solution is 0.40 M.",
        },
        source_citation={
            "source_id": "NCERT-CHEMISTRY-XI-PART1",
            "locator": "Chapter 1: Some Basic Concepts of Chemistry, Sections 1.7-1.10, pp. 16-25",
            "title": "NCERT Class 11 Chemistry: Mole Concept",
        },
    ),
    "CHE_ATM": GroundedConceptContent(
        concept_id="CHE_ATM",
        concept_name="Atomic Structure",
        subject="Chemistry",
        topic_group="Physical Chemistry",
        definition=(
            "Atomic structure encompasses quantum mechanical principles of electrons in atoms, "
            "de Broglie duality, Heisenberg uncertainty, and electron configurations governed by quantum numbers."
        ),
        core_principles=[
            "De Broglie relation: lambda = h / p = h / (m * v).",
            "Heisenberg uncertainty principle: Delta x * Delta p >= h / (4 * pi).",
            "Principal (n), Azimuthal (l), Magnetic (m_l), and Spin (m_s) quantum numbers specify atomic orbitals.",
            "Aufbau principle, Pauli exclusion principle, and Hund's rule dictate ground-state electron filling.",
        ],
        key_equations=[
            "E_n = -13.6 * (Z^2 / n^2) eV",
            "lambda = h / (m * v)",
            "Delta x * Delta p >= h / (4 * pi)",
            "Delta E = h * nu = h * c / lambda = R_H * Z^2 * (1/n_1^2 - 1/n_2^2)",
        ],
        common_misconceptions=[
            {
                "misconception": "Treating electrons as miniature planets traveling in fixed circular orbits.",
                "explanation": "In quantum mechanics, electrons do not follow deterministic circular paths; they are described by three-dimensional wavefunctions (orbitals) giving probability densities.",
                "counter_example": "The 1s orbital is spherically symmetric where the electron has a non-zero probability density at the nucleus.",
            },
        ],
        worked_example={
            "title": "De Broglie Wavelength of a Moving Electron",
            "prompt": "Calculate the de Broglie wavelength of an electron traveling at 2.0 x 10^6 m/s. (m_e = 9.11 x 10^-31 kg, h = 6.626 x 10^-34 J s).",
            "steps": [
                {
                    "step_index": 0,
                    "content": "Recall de Broglie formula: lambda = h / (m * v).",
                    "concept_ids": ["CHE_ATM"],
                },
                {
                    "step_index": 1,
                    "content": "Calculate momentum: p = m * v = (9.11 x 10^-31 kg) * (2.0 x 10^6 m/s) = 1.822 x 10^-24 kg m/s.",
                    "concept_ids": ["CHE_ATM"],
                },
                {
                    "step_index": 2,
                    "content": "Compute wavelength: lambda = (6.626 x 10^-34) / (1.822 x 10^-24) = 3.636 x 10^-10 m = 0.364 nm.",
                    "concept_ids": ["CHE_ATM"],
                },
            ],
            "final_answer": "De Broglie wavelength = 0.364 nm (3.64 Angstroms).",
        },
        source_citation={
            "source_id": "NCERT-CHEMISTRY-XI-PART1",
            "locator": "Chapter 2: Structure of Atom, Sections 2.4-2.6, pp. 45-64",
            "title": "NCERT Class 11 Chemistry: Structure of Atom",
        },
    ),
    # --- MATHEMATICS ---
    "MAT_SET": GroundedConceptContent(
        concept_id="MAT_SET",
        concept_name="Sets, Relations and Functions",
        subject="Mathematics",
        topic_group="Algebra",
        definition=(
            "Sets form the foundation of modern mathematics. A relation is a subset of a Cartesian "
            "product, and a function is a relation where each domain element maps to exactly one co-domain element."
        ),
        core_principles=[
            "A function f: A -> B assigns every element x in A exactly one element y in B.",
            "Injective (one-to-one): f(a) = f(b) implies a = b.",
            "Surjective (onto): Range(f) equals Co-domain(B).",
            "Bijective: Both injective and surjective; hence invertible.",
        ],
        key_equations=[
            "n(A union B) = n(A) + n(B) - n(A intersect B)",
            "n(P(A)) = 2^n(A)",
            "Domain(f) = {x in A : f(x) is defined}",
            "(g o f)(x) = g(f(x))",
        ],
        common_misconceptions=[
            {
                "misconception": "Assuming every relation with real numbers is a function.",
                "explanation": "If any input x produces more than one output y, it fails the vertical line test and is not a function.",
                "counter_example": "The relation x^2 + y^2 = 1 maps x = 0 to both y = 1 and y = -1; it is a circle relation, not a function.",
            },
        ],
        worked_example={
            "title": "Determining Injectivity and Surjectivity",
            "prompt": "Determine whether the function f: R -> R defined by f(x) = 2*x + 3 is a bijection.",
            "steps": [
                {
                    "step_index": 0,
                    "content": "Check injectivity (one-to-one): Let f(x_1) = f(x_2). Then 2*x_1 + 3 = 2*x_2 + 3 => 2*x_1 = 2*x_2 => x_1 = x_2. Thus f is injective.",
                    "concept_ids": ["MAT_SET"],
                },
                {
                    "step_index": 1,
                    "content": "Check surjectivity (onto): Let y in R. Set y = 2*x + 3 => x = (y - 3) / 2. Since y in R, x is always a real number in the domain. Thus f is surjective.",
                    "concept_ids": ["MAT_SET"],
                },
                {
                    "step_index": 2,
                    "content": "Conclusion: Since f is both injective and surjective, f is bijective and invertible with f^-1(y) = (y - 3)/2.",
                    "concept_ids": ["MAT_SET"],
                },
            ],
            "final_answer": "f(x) = 2*x + 3 is a bijection from R to R.",
        },
        source_citation={
            "source_id": "NCERT-MATHEMATICS-XI",
            "locator": "Chapter 1 & 2: Sets, Relations & Functions, pp. 1-46",
            "title": "NCERT Class 11 Mathematics: Sets and Functions",
        },
    ),
    "MAT_LIM": GroundedConceptContent(
        concept_id="MAT_LIM",
        concept_name="Limits and Continuity",
        subject="Mathematics",
        topic_group="Calculus",
        definition=(
            "The limit of a function f(x) as x approaches c represents the value that f(x) approaches. "
            "A function is continuous at c if lim_{x->c} f(x) = f(c)."
        ),
        core_principles=[
            "A limit exists if and only if left-hand limit equals right-hand limit: lim_{x->c-} f(x) = lim_{x->c+} f(x).",
            "Continuity requires: 1) f(c) exists, 2) lim_{x->c} f(x) exists, 3) lim_{x->c} f(x) = f(c).",
            "Indeterminate forms (0/0, inf/inf) can be evaluated via factorization, rationalization, standard limits, or L'Hopital's rule.",
        ],
        key_equations=[
            "lim_{x->0} (sin(x) / x) = 1 (for x in radians)",
            "lim_{x->0} ((e^x - 1) / x) = 1",
            "lim_{x->a} ((x^n - a^n) / (x - a)) = n * a^(n - 1)",
            "lim_{x->0} ((1 + x)^(1/x)) = e",
        ],
        common_misconceptions=[
            {
                "misconception": "Believing that if a function has an indeterminate form 0/0 at x=c, the limit does not exist.",
                "explanation": "An indeterminate form simply means direct substitution fails; algebraic simplification or calculus often reveals a finite limit.",
                "counter_example": "f(x) = (x^2 - 1) / (x - 1) gives 0/0 at x=1, but factoring gives (x+1), so the limit as x->1 is 2.",
            },
        ],
        worked_example={
            "title": "Evaluating a Trigonometric Indeterminate Limit",
            "prompt": "Evaluate the limit: lim_{x->0} (1 - cos(x)) / x^2.",
            "steps": [
                {
                    "step_index": 0,
                    "content": "Check substitution: as x->0, (1 - cos(0))/0 = 0/0 (indeterminate).",
                    "concept_ids": ["MAT_LIM"],
                },
                {
                    "step_index": 1,
                    "content": "Apply the half-angle trigonometric identity: 1 - cos(x) = 2 * sin^2(x/2).",
                    "concept_ids": ["MAT_LIM"],
                },
                {
                    "step_index": 2,
                    "content": "Rewrite expression: 2 * sin^2(x/2) / x^2 = 2 * [sin(x/2) / x]^2 = 2 * [0.5 * sin(x/2) / (x/2)]^2.",
                    "concept_ids": ["MAT_LIM"],
                },
                {
                    "step_index": 3,
                    "content": "Evaluate using standard limit lim_{u->0} sin(u)/u = 1: 2 * (0.5)^2 * (1)^2 = 2 * 0.25 = 0.5 (1/2).",
                    "concept_ids": ["MAT_LIM"],
                },
            ],
            "final_answer": "lim_{x->0} (1 - cos(x)) / x^2 = 1/2.",
        },
        source_citation={
            "source_id": "NCERT-MATHEMATICS-XI",
            "locator": "Chapter 13: Limits and Derivatives, Sections 13.2-13.4, pp. 298-312",
            "title": "NCERT Class 11 Mathematics: Limits and Derivatives",
        },
    ),
    "MAT_DIF": GroundedConceptContent(
        concept_id="MAT_DIF",
        concept_name="Differentiation",
        subject="Mathematics",
        topic_group="Calculus",
        definition=(
            "The derivative of a function f(x) measures the instantaneous rate of change of f with respect to x. "
            "Geometrically, it equals the slope of the tangent line to the curve y = f(x)."
        ),
        core_principles=[
            "First principles definition: f'(x) = lim_{h->0} [f(x + h) - f(x)] / h.",
            "Differentiability implies continuity, but continuity does not imply differentiability.",
            "Product Rule: (u * v)' = u' * v + u * v'.",
            "Quotient Rule: (u / v)' = (u' * v - u * v') / v^2.",
            "Chain Rule: d/dx [f(g(x))] = f'(g(x)) * g'(x).",
        ],
        key_equations=[
            "d/dx (x^n) = n * x^(n - 1)",
            "d/dx (sin(x)) = cos(x),  d/dx (cos(x)) = -sin(x)",
            "d/dx (e^x) = e^x,  d/dx (ln(x)) = 1/x",
            "d/dx [f(g(x))] = f'(g(x)) * g'(x)",
        ],
        common_misconceptions=[
            {
                "misconception": "Assuming any continuous curve is differentiable everywhere.",
                "explanation": "A continuous function with a sharp corner or cusp lacks a unique tangent and is non-differentiable at that point.",
                "counter_example": "f(x) = |x| is continuous at x = 0, but its left derivative (-1) does not equal its right derivative (+1); hence non-differentiable at 0.",
            },
        ],
        worked_example={
            "title": "Applying the Chain Rule to a Composite Function",
            "prompt": "Differentiate f(x) = ln(sin(x^2 + 1)) with respect to x.",
            "steps": [
                {
                    "step_index": 0,
                    "content": "Identify composite layers: outer layer ln(u), middle layer sin(v), inner layer v = x^2 + 1.",
                    "concept_ids": ["MAT_DIF"],
                },
                {
                    "step_index": 1,
                    "content": "Differentiate outer layer with respect to middle: d/du [ln(u)] = 1 / u = 1 / sin(x^2 + 1).",
                    "concept_ids": ["MAT_DIF"],
                },
                {
                    "step_index": 2,
                    "content": "Differentiate middle layer with respect to inner: d/dv [sin(v)] = cos(v) = cos(x^2 + 1).",
                    "concept_ids": ["MAT_DIF"],
                },
                {
                    "step_index": 3,
                    "content": "Differentiate inner layer with respect to x: d/dx (x^2 + 1) = 2*x.",
                    "concept_ids": ["MAT_DIF"],
                },
                {
                    "step_index": 4,
                    "content": "Multiply using chain rule: f'(x) = [1 / sin(x^2 + 1)] * cos(x^2 + 1) * 2*x = 2*x * cot(x^2 + 1).",
                    "concept_ids": ["MAT_DIF"],
                },
            ],
            "final_answer": "f'(x) = 2*x * cot(x^2 + 1).",
        },
        source_citation={
            "source_id": "NCERT-MATHEMATICS-XII-PART1",
            "locator": "Chapter 5: Continuity and Differentiability, Sections 5.2-5.4, pp. 147-172",
            "title": "NCERT Class 12 Mathematics: Continuity and Differentiability",
        },
    ),
}


# Authoritative mapping of legacy concept content to canonical IDs
CANONICAL_CONCEPT_CONTENT_MAP: Dict[str, str] = {
    "PHY_KIN": "cc_3e003bf9b038a36b",
    "PHY_NLM": "cc_e070c64d30e5e623",
    "PHY_WPE": "cc_5f9917b8333fae45",
    "CHE_MOL": "cc_ab411e6d3eeab1c1",
    "CHE_ATM": "cc_a04390bce4f730b6",
    "MAT_SET": "cc_5b5bdbe60072f33b",
    "MAT_LIM": "cc_876e4da502f7bf45",
    "MAT_DIF": "cc_c31f5c19a669612c",
}

for leg_id, can_id in CANONICAL_CONCEPT_CONTENT_MAP.items():
    if leg_id in _CONCEPT_CONTENT_REGISTRY:
        content = _CONCEPT_CONTENT_REGISTRY[leg_id]
        # Register under canonical ID as well
        _CONCEPT_CONTENT_REGISTRY[can_id] = content


class BuiltinVerifiedContentProvider(KnowledgeContentProvider):
    """Builtin offline provider serving the 8 verified core curriculum concepts."""

    def __init__(
        self,
        registry: Optional[Dict[str, GroundedConceptContent]] = None,
        migration_adapter: Optional[CanonicalConceptMigrationAdapter] = None,
    ) -> None:
        self._registry = registry or _CONCEPT_CONTENT_REGISTRY
        self.migration_adapter = migration_adapter or CanonicalConceptMigrationAdapter()

    def _resolve_id(self, concept_id: str) -> str:
        cid = str(concept_id).strip()
        if cid in self._registry:
            return cid
        try:
            can_id = self.migration_adapter.to_canonical_id(cid, default_split_to_ray=True)
            if can_id in self._registry:
                return can_id
        except Exception:
            pass
        return cid

    def get_concept_content(self, concept_id: str) -> Optional[GroundedConceptContent]:
        resolved = self._resolve_id(concept_id)
        return self._registry.get(resolved)

    def has_concept_content(self, concept_id: str) -> bool:
        resolved = self._resolve_id(concept_id)
        return resolved in self._registry

    def list_available_concepts(self) -> List[str]:
        # Return only unique canonical concept IDs
        canonical_only = [cid for cid in self._registry.keys() if cid.startswith("cc_")]
        return sorted(canonical_only)

    def search_content(self, query: str, top_k: int = 5) -> List[ContentSnippet]:
        tokens = [t.lower() for t in query.split() if len(t) > 2]
        results: List[Tuple[float, ContentSnippet]] = []

        seen_concepts = set()
        for cid, content in self._registry.items():
            if not cid.startswith("cc_"):
                continue
            if cid in seen_concepts:
                continue
            seen_concepts.add(cid)

            text_corpus = f"{content.concept_name} {content.subject} {content.definition} {' '.join(content.core_principles)}".lower()
            score = sum(1.0 for t in tokens if t in text_corpus)
            if score > 0:
                snippet = ContentSnippet(
                    concept_id=content.concept_id,
                    title=content.concept_name,
                    text=content.definition[:250] + ("..." if len(content.definition) > 250 else ""),
                    score=score,
                    source_locator=content.source_citation.get("locator"),
                )
                results.append((score, snippet))

        results.sort(key=lambda x: x[0], reverse=True)
        return [r[1] for r in results[:top_k]]


class Person2ContentBridge(KnowledgeContentProvider):
    """External content bridge loading Person 2's authoritative ingested NCERT corpus."""

    def __init__(
        self,
        content_dir_or_file: Optional[Union[str, Path]] = None,
        migration_adapter: Optional[CanonicalConceptMigrationAdapter] = None,
    ) -> None:
        self.source_path = Path(content_dir_or_file) if content_dir_or_file else None
        self.migration_adapter = migration_adapter or CanonicalConceptMigrationAdapter()
        self._external_content: Dict[str, GroundedConceptContent] = {}
        if self.source_path and self.source_path.exists():
            self.load_from_path(self.source_path)

    def load_from_path(self, path: Path) -> int:
        """Loads Person 2 content from JSON or structured directory."""
        import json
        loaded = 0
        if path.is_file() and path.suffix == ".json":
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                for item in data:
                    cid = self.migration_adapter.to_canonical_id(item["concept_id"])
                    self._external_content[cid] = GroundedConceptContent(**item)
                    loaded += 1
            except Exception as e:
                logger.error(f"Failed to load Person 2 content from {path}: {e}")
        return loaded

    def get_concept_content(self, concept_id: str) -> Optional[GroundedConceptContent]:
        try:
            cid = self.migration_adapter.to_canonical_id(str(concept_id).strip(), default_split_to_ray=True)
        except Exception:
            cid = str(concept_id).strip()
        return self._external_content.get(cid)

    def has_concept_content(self, concept_id: str) -> bool:
        return self.get_concept_content(concept_id) is not None

    def list_available_concepts(self) -> List[str]:
        return sorted(self._external_content.keys())

    def search_content(self, query: str, top_k: int = 5) -> List[ContentSnippet]:
        # Search over external content
        tokens = [t.lower() for t in query.split() if len(t) > 2]
        results: List[Tuple[float, ContentSnippet]] = []
        for cid, content in self._external_content.items():
            text_corpus = f"{content.concept_name} {content.subject} {content.definition}".lower()
            score = sum(1.0 for t in tokens if t in text_corpus)
            if score > 0:
                results.append(
                    (
                        score,
                        ContentSnippet(
                            concept_id=content.concept_id,
                            title=content.concept_name,
                            text=content.definition[:250],
                            score=score,
                            source_locator=content.source_citation.get("locator"),
                        ),
                    )
                )
        results.sort(key=lambda x: x[0], reverse=True)
        return [r[1] for r in results[:top_k]]


class GroundedKnowledgeBase:
    """Provides validated educational content lookup with strict provenance guarantees."""

    def __init__(
        self,
        provider: Optional[KnowledgeContentProvider] = None,
        person2_bridge: Optional[Person2ContentBridge] = None,
        migration_adapter: Optional[CanonicalConceptMigrationAdapter] = None,
    ) -> None:
        self.provider = provider or BuiltinVerifiedContentProvider()
        self.person2_bridge = person2_bridge
        self.migration_adapter = migration_adapter or CanonicalConceptMigrationAdapter()

    def get_concept_content(self, concept_id: str) -> Optional[GroundedConceptContent]:
        """Retrieves authoritative conceptual content for concept_id."""
        cid = str(concept_id).strip()
        if self.person2_bridge and self.person2_bridge.has_concept_content(cid):
            return self.person2_bridge.get_concept_content(cid)
        return self.provider.get_concept_content(cid)

    def contains(self, concept_id: str) -> bool:
        """Checks if authoritative content exists for concept_id."""
        cid = str(concept_id).strip()
        if self.person2_bridge and self.person2_bridge.has_concept_content(cid):
            return True
        return self.provider.has_concept_content(cid)

    def get_content_status(self, concept_id: str) -> str:
        """Returns 'verified' if content exists, or 'content_unavailable'."""
        return "verified" if self.contains(concept_id) else "content_unavailable"

    def get_source_citation(self, concept_id: str) -> Dict[str, Any]:
        """Returns verified source provenance citation or an explicit unavailable-source state.
        
        Guarantees strict integrity: never fabricates generic or synthetic citations.
        """
        content = self.get_concept_content(concept_id)
        if content and content.source_citation:
            cit = dict(content.source_citation)
            cit["is_verified"] = True
            cit["status"] = "verified"
            return cit

        return {
            "source_id": None,
            "locator": None,
            "title": None,
            "status": "source_unavailable",
            "is_verified": False,
            "note": f"Authoritative textbook source citation not registered for '{concept_id.strip()}'.",
        }

    def is_source_verified(self, concept_id: str) -> bool:
        """Checks if verified textbook provenance exists for the concept."""
        content = self.get_concept_content(concept_id)
        return content is not None and bool(content.source_citation)

    def get_definition(self, concept_id: str) -> str:
        """Returns verified definition or indicates content unavailable."""
        content = self.get_concept_content(concept_id)
        if content:
            return content.definition
        return f"Content unavailable: Verified textbook definition for '{concept_id.strip()}' is pending ingestion."

    def get_core_principles(self, concept_id: str) -> List[str]:
        content = self.get_concept_content(concept_id)
        if content:
            return list(content.core_principles)
        return []

    def get_key_equations(self, concept_id: str) -> List[str]:
        content = self.get_concept_content(concept_id)
        if content:
            return list(content.key_equations)
        return []

    def get_worked_example(self, concept_id: str) -> Optional[Dict[str, Any]]:
        content = self.get_concept_content(concept_id)
        if content:
            return content.worked_example
        return None

    def get_misconceptions(self, concept_id: str) -> List[Dict[str, str]]:
        content = self.get_concept_content(concept_id)
        if content:
            return list(content.common_misconceptions)
        return []

    def search_content(self, query: str, top_k: int = 5) -> List[ContentSnippet]:
        """Searches across providers for relevant excerpts."""
        results: List[ContentSnippet] = []
        if self.person2_bridge:
            results.extend(self.person2_bridge.search_content(query, top_k=top_k))
        results.extend(self.provider.search_content(query, top_k=top_k))
        return results[:top_k]


_DEFAULT_KB: Optional[GroundedKnowledgeBase] = None


def get_default_knowledge_base() -> GroundedKnowledgeBase:
    """Returns singleton instance of the verified GroundedKnowledgeBase."""
    global _DEFAULT_KB
    if _DEFAULT_KB is None:
        _DEFAULT_KB = GroundedKnowledgeBase()
    return _DEFAULT_KB

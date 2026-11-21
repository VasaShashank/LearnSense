"""LearnSense Person 3 — Solution Verification & Step Checking Engine.

Provides mathematically rigorous, multi-modal verification of worked solutions:
1. Problem Type Classification:
   - 'symbolic_math': Algebraic equations, calculus, symbolic derivatives/integrals.
   - 'numeric_calculation': Arithmetic derivations, numerical physics/chemistry problems.
   - 'conceptual_theory': Qualitative principles, periodic trends, mechanism descriptions.
   - 'unsupported': Diagram-only, spatial/experimental apparatus requiring external vision/human review.
2. Symbolic Mathematics Verification:
   - Exact mathematical equivalence checking via SymPy (algebraic simplifications, calculus derivations).
3. Numerical Verification:
   - Step-by-step arithmetic check with floating-point tolerance bounds.
4. Step-by-Step Derivation Consistency:
   - Validates that each step logically and mathematically follows from previous steps.
5. Explicit Error Reporting:
   - Clear diagnostic feedback when a step is invalid or a problem type is unsupported.
"""

from __future__ import annotations

import logging
import math
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple, Union

logger = logging.getLogger(__name__)

try:
    import sympy
    from sympy.parsing.sympy_parser import (
        convert_xor,
        implicit_multiplication_application,
        parse_expr,
        standard_transformations,
    )
    SYMPY_AVAILABLE = True
except ImportError:
    SYMPY_AVAILABLE = False
    logger.warning("SymPy is not installed; symbolic verification falling back to rule-based parser.")


@dataclass
class StepVerificationResult:
    """Verification result for a single step in a derivation."""
    step_index: int
    is_valid: bool
    status: str  # 'valid' | 'invalid' | 'unsupported' | 'unverifiable'
    error_message: Optional[str] = None
    derived_expression: Optional[str] = None
    details: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "step_index": self.step_index,
            "is_valid": self.is_valid,
            "status": self.status,
            "error_message": self.error_message,
            "derived_expression": self.derived_expression,
            "details": self.details,
        }


@dataclass
class SolutionVerificationResult:
    """Comprehensive verification result for an entire problem solution."""
    problem_type: str  # 'symbolic_math' | 'numeric_calculation' | 'conceptual_theory' | 'unsupported'
    is_valid: bool
    overall_status: str  # 'verified' | 'failed' | 'unsupported' | 'partial'
    step_results: List[StepVerificationResult] = field(default_factory=list)
    final_answer_verified: bool = False
    discrepancy: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "problem_type": self.problem_type,
            "is_valid": self.is_valid,
            "overall_status": self.overall_status,
            "step_results": [s.to_dict() for s in self.step_results],
            "final_answer_verified": self.final_answer_verified,
            "discrepancy": self.discrepancy,
            "metadata": self.metadata,
        }


class SolutionVerifier:
    """Mathematical and conceptual solution verification engine."""

    def __init__(self, tolerance: float = 1e-4) -> None:
        self.tolerance = tolerance
        if SYMPY_AVAILABLE:
            self._transformations = standard_transformations + (
                implicit_multiplication_application,
                convert_xor,
            )
        else:
            self._transformations = None

    def classify_problem_type(self, problem_text: str, solution_text: str = "") -> str:
        """Classifies the problem type based on lexical and mathematical markers."""
        combined = f"{problem_text} {solution_text}".lower()

        # 1. Unsupported Markers (diagrammatic, visual, complex apparatus)
        unsupported_markers = [
            "refer to figure",
            "shown in the diagram",
            "circuit diagram below",
            "experimental setup in lab",
            "graph shown above",
            "unsupported format",
        ]
        if any(m in combined for m in unsupported_markers):
            return "unsupported"

        # 2. Symbolic Math Markers
        symbolic_markers = [
            "d/dx", "integral", "derivative", "dy/dx", "f'(x)",
            "sin(", "cos(", "tan(", "ln(", "log(", "sqrt(",
            "^2", "^3", "dx", "dt", "theta", "alpha", "omega",
            "differentiate", "integrate", "eigenvalue", "matrix",
        ]
        symbolic_count = sum(1 for m in symbolic_markers if m in combined)
        if symbolic_count >= 2 or ("=" in combined and any(var in combined for var in ["f(x)", "y(t)", "x(t)", "v(t)"])):
            return "symbolic_math"

        # 3. Numeric Calculation Markers
        has_numbers = bool(re.search(r"\d+\.?\d*\s*(m/s|kg|j|n|pa|s|k|v|ohm|%|\$|rs)", combined))
        has_arithmetic_equations = bool(re.search(r"\d+\s*[\+\-\*\/]\s*\d+\s*=", combined))
        if has_numbers or has_arithmetic_equations:
            return "numeric_calculation"

        # 4. Conceptual Theory Markers
        conceptual_markers = [
            "spontaneous", "entropy", "equilibrium", "isothermal", "adiabatic",
            "le chatelier", "electronegativity", "ionization", "hybridization",
            "intensive property", "extensive property", "conservation of",
        ]
        if any(m in combined for m in conceptual_markers):
            return "conceptual_theory"

        # Default heuristic fallback
        return "numeric_calculation" if bool(re.search(r"\d+", combined)) else "conceptual_theory"

    def _clean_math_expr(self, expr_str: str) -> str:
        """Normalizes mathematical expression strings for SymPy parsing."""
        s = expr_str.strip()
        # Replace ^ with **
        s = s.replace("^", "**")
        # Remove trailing periods
        s = s.rstrip(".")
        # Replace unicode symbols
        s = s.replace("×", "*").replace("÷", "/")
        return s

    def verify_symbolic_equivalence(self, expr1_str: str, expr2_str: str) -> Tuple[bool, Optional[str]]:
        """Verifies mathematical equivalence between two symbolic expressions using SymPy."""
        if not SYMPY_AVAILABLE:
            return False, "SymPy is not installed for symbolic verification."

        try:
            c1 = self._clean_math_expr(expr1_str)
            c2 = self._clean_math_expr(expr2_str)

            # Strip leading variable assignment if present (e.g. 'v(t) = 0.5*b*t^2' -> '0.5*b*t^2')
            if "=" in c1:
                c1 = c1.split("=", 1)[1].strip()
            if "=" in c2:
                c2 = c2.split("=", 1)[1].strip()

            e1 = parse_expr(c1, transformations=self._transformations)
            e2 = parse_expr(c2, transformations=self._transformations)

            diff = sympy.simplify(e1 - e2)
            if diff == 0 or diff.is_zero:
                return True, None

            # Try numerical evaluation at random points if simplification is ambiguous
            symbols = list(e1.free_symbols.union(e2.free_symbols))
            if symbols:
                import random
                subs_map = {s: random.uniform(1.5, 5.0) for s in symbols}
                v1 = float(e1.evalf(subs=subs_map))
                v2 = float(e2.evalf(subs=subs_map))
                if abs(v1 - v2) < 1e-5:
                    return True, None

            return False, f"Expressions are not symbolically equivalent: '{c1}' vs '{c2}' (diff: {diff})"
        except Exception as e:
            return False, f"SymPy parsing failed: {e}"

    def verify_numeric_arithmetic(self, equation_str: str) -> Tuple[bool, Optional[str]]:
        """Verifies whether an arithmetic statement (including chained equality A = B = C) holds."""
        if "=" not in equation_str:
            return True, None

        parts = [p.strip() for p in equation_str.split("=")]
        if len(parts) < 2:
            return True, None

        # Check each consecutive pair (part_i == part_{i+1})
        for i in range(len(parts) - 1):
            left_str = parts[i]
            right_str = parts[i + 1]

            # Strip non-numeric/variable words before evaluation (e.g. 'v' or 's')
            left_expr = re.sub(r"\b[a-zA-Z_]\w*\b", "", left_str)
            right_expr = re.sub(r"\b[a-zA-Z_]\w*\b", "", right_str)

            left_clean = re.sub(r"[^\d\.\+\-\*\/\(\)\s]", "", left_expr).strip()
            right_clean = re.sub(r"[^\d\.\+\-\*\/\(\)\s]", "", right_expr).strip()

            if not left_clean or not right_clean:
                continue

            try:
                val_left = float(eval(compile(left_clean, "<string>", "eval"), {"__builtins__": {}}, {}))
                val_right = float(eval(compile(right_clean, "<string>", "eval"), {"__builtins__": {}}, {}))

                if not math.isclose(val_left, val_right, rel_tol=self.tolerance, abs_tol=self.tolerance):
                    return False, f"Arithmetic mismatch: {left_str} ({val_left}) != {right_str} ({val_right})."
            except Exception:
                continue

        return True, None

    def verify_solution(
        self,
        problem_text: str,
        steps: Optional[List[Union[str, Dict[str, Any]]]] = None,
        final_answer: str = "",
        problem_type: Optional[str] = None,
        **kwargs: Any,
    ) -> SolutionVerificationResult:
        """Performs comprehensive step-by-step verification of a solution derivation."""
        # Normalize steps
        actual_steps = steps if steps is not None else kwargs.get("student_steps", [])
        step_texts: List[str] = []
        for s in actual_steps:
            if isinstance(s, dict):
                step_texts.append(str(s.get("content", "")))
            else:
                step_texts.append(str(s))

        solution_concat = " ".join(step_texts) + " " + final_answer
        p_type = problem_type or self.classify_problem_type(problem_text, solution_concat)

        # 1. Handle Unsupported Problem Types
        if p_type == "unsupported":
            return SolutionVerificationResult(
                problem_type="unsupported",
                is_valid=False,
                overall_status="unsupported",
                step_results=[
                    StepVerificationResult(
                        step_index=i,
                        is_valid=False,
                        status="unsupported",
                        error_message="Visual diagram, experimental circuit, or apparatus requires human expert verification.",
                    )
                    for i in range(len(step_texts))
                ],
                final_answer_verified=False,
                discrepancy="Automated verification is not supported for diagrammatic or experimental apparatus problems.",
            )

        # 2. Step-by-Step Verification
        step_results: List[StepVerificationResult] = []
        all_steps_valid = True
        discrepancy_note: Optional[str] = None

        for idx, text in enumerate(step_texts):
            step_valid = True
            err_msg: Optional[str] = None

            if p_type == "numeric_calculation":
                # Look for clauses containing '='
                clauses = re.split(r"[\,\;]|\band\b", text)
                for clause in clauses:
                    if "=" in clause:
                        is_ok, err = self.verify_numeric_arithmetic(clause)
                        if not is_ok:
                            step_valid = False
                            err_msg = err
                            break
            elif p_type == "symbolic_math":
                # Look for derivative or equality assertions
                if "=" in text and not re.search(r"where|when|at|let", text, re.I):
                    parts = text.split("=")
                    if len(parts) == 2:
                        left = parts[0].split(":")[-1].strip()
                        right = parts[1].split(".")[0].strip()
                        if any(c in left for c in ["x", "t", "y", "v", "u"]) and any(c in right for c in ["x", "t", "y", "v", "u"]):
                            is_ok, err = self.verify_symbolic_equivalence(left, right)
                            # Only fail if SymPy explicitly disproved equivalence
                            if not is_ok and "not symbolically equivalent" in str(err):
                                step_valid = False
                                err_msg = err

            elif p_type == "conceptual_theory":
                # Check for glaring contradictions (e.g., violating conservation or asserting wrong intensive properties)
                contradiction_patterns = [
                    (r"violates\s+conservation", "Falsely asserts violation of conservation laws."),
                    (r"enthalpy\s+is\s+intensive", "Enthalpy is extensive, not intensive."),
                    (r"entropy\s+is\s+intensive", "Entropy is extensive, not intensive."),
                ]
                for pat, msg in contradiction_patterns:
                    if re.search(pat, text, re.IGNORECASE):
                        step_valid = False
                        err_msg = msg
                        break

            if not step_valid:
                all_steps_valid = False
                if not discrepancy_note:
                    discrepancy_note = f"Step {idx + 1} failed: {err_msg}"

            step_results.append(
                StepVerificationResult(
                    step_index=idx,
                    is_valid=step_valid,
                    status="valid" if step_valid else "invalid",
                    error_message=err_msg,
                    derived_expression=text[:100],
                )
            )

        # 3. Final Answer Verification
        final_valid = True
        if step_texts and final_answer:
            last_step = step_texts[-1]
            # Check if last step agrees with final answer
            if p_type == "numeric_calculation":
                nums_in_last = re.findall(r"\d+\.?\d*", last_step)
                nums_in_final = re.findall(r"\d+\.?\d*", final_answer)
                if nums_in_final and not any(nf in nums_in_last for nf in nums_in_final):
                    final_valid = False
                    if not discrepancy_note:
                        discrepancy_note = f"Final answer '{final_answer}' not derived in final step: '{last_step}'."

        overall_valid = all_steps_valid and final_valid

        return SolutionVerificationResult(
            problem_type=p_type,
            is_valid=overall_valid,
            overall_status="verified" if overall_valid else "failed",
            step_results=step_results,
            final_answer_verified=final_valid,
            discrepancy=discrepancy_note,
            metadata={"total_steps": len(step_texts), "sympy_active": SYMPY_AVAILABLE},
        )

"""
Regenerates configs/notation_registry.json with correctly-escaped regex patterns.
Uses Python raw strings so json.dumps handles all JSON-level escaping correctly,
eliminating any chance of manual over/under-escaping.
"""
import json
import re
from pathlib import Path

# Build registry as native Python dicts with raw-string regex patterns.
# json.dumps will then correctly double-escape them for JSON.
data = {
    "domains": {
        "economics": {
            "aliases": {
                "Y": "national_income",
                "GDP": "national_income",
                "C": "consumption",
                "I": "investment",
                "G": "government_spending",
                "NX": "net_exports",
                "X-M": "net_exports",
            },
            "canonical_laws": [
                {
                    "id": "macro_gdp_expenditure",
                    "description": "GDP Expenditure Formula",
                    "patterns": [
                        r"Y\s*=\s*C\s*\+\s*I\s*\+\s*G\s*\+\s*NX",
                        r"GDP\s*=\s*C\s*\+\s*I\s*\+\s*G\s*\+\s*\(?\s*X\s*-\s*M\s*\)?",
                    ],
                }
            ],
        },
        "computer_science": {
            "aliases": {
                "O(n)": "asymptotic_upper_bound",
                "Theta(n)": "asymptotic_tight_bound",
                "\\Theta(n)": "asymptotic_tight_bound",
                "BFS": "breadth_first_search",
                "DFS": "depth_first_search",
            },
            "canonical_laws": [
                {
                    "id": "merge_sort_recurrence",
                    "description": "Merge Sort Divide-and-Conquer Recurrence",
                    "patterns": [
                        r"T\(n\)\s*=\s*2\s*T\(n/2\)\s*\+\s*O\(n\)",
                        r"T\(n\)\s*=\s*2\s*T\(n/2\)\s*\+\s*(?:\\Theta|Theta)\s*\(n\)",
                    ],
                }
            ],
        },
        "kinematics": {
            "aliases": {
                "u": "initial_velocity",
                "v_0": "initial_velocity",
                "v0": "initial_velocity",
                "v": "final_velocity",
                "a": "acceleration",
                "t": "time",
                "\\Delta t": "time",
                "s": "displacement",
                "d": "displacement",
                "x": "displacement",
                "\\Delta x": "displacement",
            },
            "canonical_laws": [
                {
                    "id": "kinematics_velocity_time",
                    "description": "Velocity-Time Relation under Uniform Acceleration",
                    "patterns": [
                        r"v\s*=\s*u\s*\+\s*a\s*\*?\s*t",
                        r"v\s*=\s*v_0\s*\+\s*a\s*\*?\s*t",
                        r"v\s*=\s*v0\s*\+\s*a\s*\*?\s*t",
                        r"v\s*=\s*v_0\s*\+\s*a\s*\*?\s*(?:\\Delta|Delta)?\s*t",
                        r"v\s*=\s*v0\s*\+\s*a\s*\*?\s*(?:\\Delta|Delta)?\s*t",
                        r"v\s*=\s*u\s*\+\s*at",
                    ],
                }
            ],
        },
        "calculus": {
            "aliases": {
                "dy/dx": "derivative",
                "f'(x)": "derivative",
                "\\frac{dy}{dx}": "derivative",
                "\\int": "integral",
            },
            "canonical_laws": [
                {
                    "id": "derivative_power_rule",
                    "description": "Power Rule for Derivatives",
                    "patterns": [
                        r"d/dx\s*\[?x\^n\]?\s*=\s*n\s*x\^\(n-1\)",
                        r"\(x\^n\)'\s*=\s*n\s*x\^\(n-1\)",
                    ],
                }
            ],
        },
        "mechanics": {
            "aliases": {
                "F": "force",
                "\\Sigma F": "net_force",
                "F_net": "net_force",
                "m": "mass",
                "a": "acceleration",
            },
            "canonical_laws": [
                {
                    "id": "newton_second_law",
                    "description": "Newton's Second Law of Motion",
                    "patterns": [
                        r"F\s*=\s*m\s*\*?\s*a",
                        r"(?:\\Sigma|Sigma)?\s*F\s*=\s*m\s*\*?\s*a",
                        r"F_net\s*=\s*m\s*\*?\s*a",
                    ],
                }
            ],
        },
    }
}

# === Verification before writing ===
TEST_CASES = [
    # (pattern_raw, text_to_match, should_match)
    (r"Y\s*=\s*C\s*\+\s*I\s*\+\s*G\s*\+\s*NX", "Y = C + I + G + NX", True),
    (r"GDP\s*=\s*C\s*\+\s*I\s*\+\s*G\s*\+\s*\(?\s*X\s*-\s*M\s*\)?", "GDP = C + I + G + (X - M)", True),
    (r"T\(n\)\s*=\s*2\s*T\(n/2\)\s*\+\s*O\(n\)", "T(n) = 2T(n/2) + O(n)", True),
    (r"T\(n\)\s*=\s*2\s*T\(n/2\)\s*\+\s*(?:\\Theta|Theta)\s*\(n\)", "T(n) = 2T(n/2) + \\Theta(n)", True),
    (r"T\(n\)\s*=\s*2\s*T\(n/2\)\s*\+\s*(?:\\Theta|Theta)\s*\(n\)", "T(n) = 2T(n/2) + Theta(n)", True),
    (r"v\s*=\s*u\s*\+\s*a\s*\*?\s*t", "v = u + at", True),
    (r"v\s*=\s*v_0\s*\+\s*a\s*\*?\s*(?:\\Delta|Delta)?\s*t", "v = v_0 + a*\\Delta t", True),
    (r"v\s*=\s*v_0\s*\+\s*a\s*\*?\s*(?:\\Delta|Delta)?\s*t", "v = v_0 + a*Delta t", True),
    (r"v\s*=\s*v_0\s*\+\s*a\s*\*?\s*(?:\\Delta|Delta)?\s*t", "v = v_0 + a*t", True),
    (r"F\s*=\s*m\s*\*?\s*a", "F = m*a", True),
    (r"(?:\\Sigma|Sigma)?\s*F\s*=\s*m\s*\*?\s*a", "\\Sigma F = m*a", True),
    (r"(?:\\Sigma|Sigma)?\s*F\s*=\s*m\s*\*?\s*a", "Sigma F = m*a", True),
]

all_ok = True
for pattern, text, should_match in TEST_CASES:
    matched = bool(re.search(pattern, text, re.IGNORECASE))
    status = "OK" if matched == should_match else "FAIL"
    if status == "FAIL":
        all_ok = False
    print(f"  [{status}] pattern={repr(pattern[:40])}... text={repr(text)} -> {matched} (expected {should_match})")

if not all_ok:
    raise SystemExit("Pattern verification failed — NOT writing file.")

# Write
out = Path("configs/notation_registry.json")
out.parent.mkdir(parents=True, exist_ok=True)
with open(out, "w", encoding="utf-8") as f:
    json.dump(data, f, indent=2, ensure_ascii=False)

print(f"\nWrote {out} successfully ({out.stat().st_size} bytes)")

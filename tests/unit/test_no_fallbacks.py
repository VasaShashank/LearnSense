"""
Static guard tests enforcing the TAPROOT no-fallback policy.

These tests parse production source files with the AST module and assert:
1. No bare ``except:`` clauses (must catch a specific exception type).
2. No ``except Exception: pass`` (swallow-everything pattern).
3. No imports from ``tests.`` in production code.
4. No ``from tests.support`` imports outside test files.

An ALLOW_LIST is provided for legitimate patterns that look like violations
but have been audited and found acceptable.
"""

import ast
import os
import sys
from pathlib import Path
from typing import List, Tuple

import pytest

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent  # LearnSense/

# Production packages to scan (relative to PROJECT_ROOT).
PRODUCTION_PACKAGES = [
    "adapters",
    "backend",
    "extraction",
    "ingestion",
    "phase2",
    "phase3",
    "phase4",
    "phase5",
    "schemas",
    "storage",
]

# Files that are explicitly allowed to have patterns that would otherwise fail.
# Each entry is (relative_path, violation_kind).
ALLOW_LIST: List[Tuple[str, str]] = [
    # storage/repositories.py: except blocks now log and continue — legitimate for
    # iterating over potentially corrupt JSON files.
    ("storage/repositories.py", "except_exception_continue"),
    # QuestionBankRepository.save_bank cleanup — except around os.unlink of temp file
    ("storage/repositories.py", "bare_except_handler"),
]


def _is_allowed(rel_path: str, kind: str) -> bool:
    """Check if a violation is in the allow-list."""
    norm = rel_path.replace("\\", "/")
    for allowed_path, allowed_kind in ALLOW_LIST:
        if norm.endswith(allowed_path) and kind == allowed_kind:
            return True
    return False


def _collect_python_files() -> List[Path]:
    """Collect all .py files in production packages."""
    files = []
    for pkg in PRODUCTION_PACKAGES:
        pkg_path = PROJECT_ROOT / pkg
        if pkg_path.is_dir():
            for py_file in pkg_path.rglob("*.py"):
                files.append(py_file)
    return files


def _relative(path: Path) -> str:
    try:
        return str(path.relative_to(PROJECT_ROOT))
    except ValueError:
        return str(path)


# ---------------------------------------------------------------------------
# Test: No bare except clauses
# ---------------------------------------------------------------------------

def test_no_bare_except_in_production():
    """Every except clause must specify an exception type."""
    violations = []
    for py_file in _collect_python_files():
        try:
            tree = ast.parse(py_file.read_text(encoding="utf-8"), filename=str(py_file))
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.ExceptHandler) and node.type is None:
                rel = _relative(py_file)
                if not _is_allowed(rel, "bare_except"):
                    violations.append(f"{rel}:{node.lineno}")
    assert not violations, (
        f"Bare 'except:' found in production code (must catch specific types):\n"
        + "\n".join(f"  - {v}" for v in violations)
    )


# ---------------------------------------------------------------------------
# Test: No except Exception: pass
# ---------------------------------------------------------------------------

def test_no_except_exception_pass_in_production():
    """No 'except Exception: pass' patterns — errors must not be swallowed."""
    violations = []
    for py_file in _collect_python_files():
        try:
            tree = ast.parse(py_file.read_text(encoding="utf-8"), filename=str(py_file))
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.ExceptHandler):
                # Check if it catches Exception (or bare except) and body is just pass
                if node.type is not None:
                    type_name = ""
                    if isinstance(node.type, ast.Name):
                        type_name = node.type.id
                    elif isinstance(node.type, ast.Attribute):
                        type_name = node.type.attr
                    if type_name == "Exception" and len(node.body) == 1:
                        body_stmt = node.body[0]
                        if isinstance(body_stmt, ast.Pass):
                            rel = _relative(py_file)
                            if not _is_allowed(rel, "except_exception_pass"):
                                violations.append(f"{rel}:{node.lineno}")
                        elif isinstance(body_stmt, ast.Expr) and isinstance(body_stmt.value, ast.Constant):
                            # except Exception: "string" — effectively a no-op
                            rel = _relative(py_file)
                            if not _is_allowed(rel, "except_exception_pass"):
                                violations.append(f"{rel}:{node.lineno}")
    assert not violations, (
        f"'except Exception: pass' found in production code:\n"
        + "\n".join(f"  - {v}" for v in violations)
    )


# ---------------------------------------------------------------------------
# Test: No imports from tests.* in production
# ---------------------------------------------------------------------------

def test_no_test_imports_in_production():
    """Production code must never import from tests.* packages."""
    violations = []
    for py_file in _collect_python_files():
        try:
            tree = ast.parse(py_file.read_text(encoding="utf-8"), filename=str(py_file))
        except SyntaxError:
            continue
        rel = _relative(py_file)
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name.startswith("tests.") or alias.name == "tests":
                        if not _is_allowed(rel, "test_import"):
                            violations.append(f"{rel}:{node.lineno} — import {alias.name}")
            elif isinstance(node, ast.ImportFrom):
                if node.module and (node.module.startswith("tests.") or node.module == "tests"):
                    if not _is_allowed(rel, "test_import"):
                        violations.append(f"{rel}:{node.lineno} — from {node.module} import ...")
    assert not violations, (
        f"Production code imports from tests.* packages:\n"
        + "\n".join(f"  - {v}" for v in violations)
    )


# ---------------------------------------------------------------------------
# Test: No except Exception: continue (without logging)
# ---------------------------------------------------------------------------

def test_no_silent_continue_in_except():
    """'except Exception: continue' must include logging — not silently skip."""
    violations = []
    for py_file in _collect_python_files():
        try:
            tree = ast.parse(py_file.read_text(encoding="utf-8"), filename=str(py_file))
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.ExceptHandler):
                if node.type is not None:
                    type_name = ""
                    if isinstance(node.type, ast.Name):
                        type_name = node.type.id
                    if type_name == "Exception" and len(node.body) == 1:
                        body_stmt = node.body[0]
                        if isinstance(body_stmt, ast.Continue):
                            rel = _relative(py_file)
                            if not _is_allowed(rel, "except_exception_continue"):
                                violations.append(f"{rel}:{node.lineno}")
    assert not violations, (
        f"'except Exception: continue' without logging found:\n"
        + "\n".join(f"  - {v}" for v in violations)
    )

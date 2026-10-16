"""
Generalized Notation, Terminology, and Formula Equivalence Engine.
Part of TAPROOT / LearnSense Phase 3/4 Resource Intelligence (§9.4).

Generalizable across all academic disciplines (STEM, Social Sciences,
Humanities, Economics, Law, Medicine, Computer Science, and Arts).
"""

import json
import logging
import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

logger = logging.getLogger(__name__)

DEFAULT_CONFIG_PATH = Path("configs/notation_registry.json")


class NotationMatcher:
    """
    Generalized engine that evaluates notation compatibility, mathematical formula equivalence,
    and terminology alignment across ANY academic discipline.

    Combines:
    1. Dynamic document-extracted variable and alias definitions.
    2. Zero-shot LLM semantic equivalence for cross-subject terminology translation.
    3. Generalized structural variable alignment (token and syntax structure).
    4. Extensible, data-driven domain registries (loaded from external JSON config, not hardcoded in code).
    """

    def __init__(
        self,
        config_path: Optional[Path] = None,
        custom_aliases: Optional[Dict[str, Dict[str, str]]] = None,
        llm_adapter: Optional[Any] = None,
    ):
        self.aliases: Dict[str, Dict[str, str]] = {}
        self.canonical_laws: List[Dict[str, Any]] = []
        self._llm_adapter = llm_adapter

        # Load data-driven registry from external configuration file
        cfg_file = config_path or DEFAULT_CONFIG_PATH
        if cfg_file.exists():
            try:
                with open(cfg_file, "r", encoding="utf-8") as f:
                    cfg_data = json.load(f)
                    for domain, d_info in cfg_data.get("domains", {}).items():
                        self.aliases[domain] = {}
                        for k, v in d_info.get("aliases", {}).items():
                            self.aliases[domain][k.strip()] = v
                            self.aliases[domain][k.strip().replace(" ", "")] = v
                        for law in d_info.get("canonical_laws", []):
                            self.canonical_laws.append(law)
            except Exception as exc:
                logger.warning("Could not load notation registry from %s: %s", cfg_file, exc)

        # Merge runtime/custom aliases if provided by course or institution
        if custom_aliases:
            for domain, mapping in custom_aliases.items():
                self.aliases.setdefault(domain, {})
                for k, v in mapping.items():
                    self.aliases[domain][k.strip()] = v
                    self.aliases[domain][k.strip().replace(" ", "")] = v

    def normalize_symbol(
        self, symbol: str, domain: Optional[str] = None, context_glossary: Optional[Dict[str, str]] = None
    ) -> str:
        """
        Resolves a symbol or technical term to its canonical concept meaning.
        Checks:
        1. User's document-derived context glossary.
        2. Configured domain registries.
        3. Raw token fallback.
        """
        raw = symbol.strip()
        no_space = raw.replace(" ", "")

        # 1. Check document's own extracted glossary/definitions
        if context_glossary:
            if raw in context_glossary:
                return context_glossary[raw]
            if no_space in context_glossary:
                return context_glossary[no_space]

        # 2. Check domain registries
        if domain and domain in self.aliases:
            if raw in self.aliases[domain]:
                return self.aliases[domain][raw]
            if no_space in self.aliases[domain]:
                return self.aliases[domain][no_space]

        for d, mapping in self.aliases.items():
            if raw in mapping:
                return mapping[raw]
            if no_space in mapping:
                return mapping[no_space]

        return no_space.lower()

    def identify_canonical_law(self, formula_text: str) -> Optional[str]:
        """Checks if a formula matches a recognized canonical law in the registry."""
        clean = formula_text.strip().replace("\\,", "").replace("\\ ", "")
        for item in self.canonical_laws:
            for pattern in item.get("patterns", []):
                if re.search(pattern, clean, re.IGNORECASE):
                    return item.get("id")
        return None

    def are_formulas_equivalent(
        self,
        formula_a: str,
        formula_b: str,
        domain: Optional[str] = None,
        context_glossary: Optional[Dict[str, str]] = None,
    ) -> Tuple[bool, float, str]:
        """
        Determines whether two formulas or technical notations express the same underlying concept.
        Works across any domain (Economics, Computer Science, Biology, Physics, Calculus, etc.).
        """
        clean_a = " ".join(formula_a.strip().split())
        clean_b = " ".join(formula_b.strip().split())

        # Exact match
        if clean_a.lower() == clean_b.lower():
            return True, 1.0, "Identical notation"

        # 1. Check data-driven canonical registry
        canon_a = self.identify_canonical_law(clean_a)
        canon_b = self.identify_canonical_law(clean_b)
        if canon_a and canon_b and canon_a == canon_b:
            diff_expl = self._explain_symbol_differences(clean_a, clean_b, domain, context_glossary)
            return True, 0.95, f"Equivalent canonical relation ({canon_a}). {diff_expl}".strip()

        # 2. Structural variable extraction & Jaccard alignment (general mathematical / formal syntax)
        tokens_a = self._extract_variables(clean_a)
        tokens_b = self._extract_variables(clean_b)

        normalized_a = {self.normalize_symbol(t, domain, context_glossary) for t in tokens_a}
        normalized_b = {self.normalize_symbol(t, domain, context_glossary) for t in tokens_b}

        if normalized_a and normalized_b:
            intersection = normalized_a & normalized_b
            union = normalized_a | normalized_b
            jaccard = len(intersection) / len(union) if union else 0.0

            if jaccard >= 0.70:
                explanation = self._explain_symbol_differences(clean_a, clean_b, domain, context_glossary)
                return True, round(0.70 + 0.25 * jaccard, 2), explanation

        # 3. LLM-backed zero-shot semantic matching if live LLM is active
        if self._llm_adapter is not None:
            try:
                llm_res = self._check_equivalence_with_llm(clean_a, clean_b, domain)
                if llm_res:
                    return llm_res
            except Exception as exc:
                logger.debug("LLM semantic notation matching skipped: %s", exc)

        return False, 0.10, "Notation and structure differ"

    def calculate_notation_compatibility(
        self,
        source_formulas: List[str],
        resource_formulas: List[str],
        domain: Optional[str] = None,
        context_glossary: Optional[Dict[str, str]] = None,
    ) -> Tuple[float, str, List[str]]:
        """
        Compares expressions/terminology from course material against an external resource.
        Returns (compatibility_score, explanation, matched_expressions).
        """
        if not source_formulas or not resource_formulas:
            return 0.75, "Neutral notation compatibility (no conflicting expressions detected)", []

        best_scores = []
        explanations = []
        matched = []

        for s_f in source_formulas:
            best_match_score = 0.0
            best_match_expl = ""
            best_match_str = ""
            for r_f in resource_formulas:
                equiv, score, expl = self.are_formulas_equivalent(s_f, r_f, domain, context_glossary)
                if score > best_match_score:
                    best_match_score = score
                    best_match_expl = expl
                    best_match_str = f"{s_f} ≈ {r_f}"

            if best_match_score > 0.0:
                best_scores.append(best_match_score)
                if best_match_score >= 0.70 and best_match_str:
                    matched.append(best_match_str)
                    if best_match_expl and best_match_expl not in explanations:
                        explanations.append(best_match_expl)

        if not best_scores:
            return 0.50, "Standard notation compatibility", []

        avg_score = sum(best_scores) / len(best_scores)
        explanation = "; ".join(explanations) if explanations else "Notation compatible"
        return round(avg_score, 2), explanation, matched

    def _extract_variables(self, text: str) -> Set[str]:
        """Extracts variables, identifiers, or technical terms from an expression."""
        cleaned = re.sub(r"[0-9\+\-\*\/\=\(\)\^\,\;\[\]\{\}]", " ", text)
        cleaned = re.sub(r"\\(?:frac|sqrt|sin|cos|tan|log|ln|lim|sum|int|Theta|Delta)", " ", cleaned)
        tokens = [t.strip() for t in cleaned.split() if len(t.strip()) > 0]
        return set(tokens)

    def _explain_symbol_differences(
        self,
        formula_a: str,
        formula_b: str,
        domain: Optional[str],
        context_glossary: Optional[Dict[str, str]],
    ) -> str:
        vars_a = self._extract_variables(formula_a)
        vars_b = self._extract_variables(formula_b)
        mappings = []

        for va in vars_a:
            mean_a = self.normalize_symbol(va, domain, context_glossary)
            for vb in vars_b:
                mean_b = self.normalize_symbol(vb, domain, context_glossary)
                if mean_a == mean_b and va != vb:
                    mappings.append(f"uses '{vb}' for {mean_a.replace('_', ' ')} (where your source uses '{va}')")

        if mappings:
            return "Video " + ", and ".join(mappings[:2])
        return "Notational conventions align closely"

    def _check_equivalence_with_llm(
        self, text_a: str, text_b: str, domain: Optional[str]
    ) -> Optional[Tuple[bool, float, str]]:
        """Zero-shot LLM semantic notation & terminology alignment for arbitrary disciplines."""
        prompt = (
            f"You are an expert pedagogical semantic analyst. Compare these two notations/formulas:\n"
            f"Expression A (Course Material): {text_a}\n"
            f"Expression B (External Video/Resource): {text_b}\n"
            f"Subject Context: {domain or 'General'}\n\n"
            f"Determine if they represent the same underlying concept or formula under different "
            f"notation/conventions. Respond strictly with JSON having keys:\n"
            f"is_equivalent (boolean), compatibility_score (float 0.0 to 1.0), explanation (string concise)."
        )
        schema = {
            "is_equivalent": "boolean",
            "compatibility_score": "number",
            "explanation": "string",
        }
        res = self._llm_adapter.generate_json(prompt, schema)
        if isinstance(res, dict) and "is_equivalent" in res:
            return (
                bool(res.get("is_equivalent")),
                float(res.get("compatibility_score", 0.5)),
                str(res.get("explanation", "")),
            )
        return None

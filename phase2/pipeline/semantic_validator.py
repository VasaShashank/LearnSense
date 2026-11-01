"""
Semantic Concept Validator & Normalization Engine for Taproot Phase 2.
Evaluates concept candidates, rejects formula fragments and OCR noise,
preserves legitimate curriculum subtopics, and normalizes canonical concept names.
"""

from __future__ import annotations

import re
import unicodedata
from enum import Enum
from typing import Any, Dict, List, Optional, Set, Tuple


class ConceptValidationOutcome(str, Enum):
    VALID_CONCEPT = "valid_concept"
    REPAIRED_CONCEPT = "repaired_concept"
    ALIAS_VARIANT = "alias_variant"
    REJECTED_NOISE = "rejected_noise"


class RejectionCategory(str, Enum):
    EQUATION_FRAGMENT = "equation_fragment"
    DIAGRAM_VARIABLE = "diagram_variable"
    GENERIC_WORD = "generic_word"
    NON_CONCEPTUAL_DESCRIPTIVE = "non_conceptual_descriptive"
    ACTION_VERB_PHRASE = "action_verb_phrase"
    INCOMPLETE_PHRASE = "incomplete_phrase"
    SENTENCE_FRAGMENT = "sentence_fragment"
    OCR_ARTIFACT = "ocr_artifact"


# Known mathematical and physics equation tokens that are NOT concept names
_EQUATION_FRAGMENTS: Set[str] = {
    "mg sin", "mg cos", "mg sin theta", "mg cos theta", "mg sin θ", "mg cos θ",
    "tan phi", "tan θ", "tan theta", "tan φ", "tan", "sin", "cos",
    "f = ma", "f=ma", "f_net = ma", "fnet = ma", "dp/dt", "dp dt",
    "sigma f", "sigma fx", "sigma fy", "sigma fz", "sigma f_x", "sigma f_y", "sigma f_z",
    "sigma f x", "sigma f y", "sigma f z", "fx", "fy", "fz",
    "max", "may", "maz", "m ax", "m ay", "m az",
    "fmax", "f max", "f_max", "fk", "f_k", "fs", "f_s",
    "ar", "a_r", "at", "a_t", "a net", "a_net", "dv dt", "dv/dt",
    "v^2/r", "v2/r", "omega^2 r", "omega r", "r alpha",
    "mu s", "mu_s", "mu k", "mu_k", "mu n", "mu_n", "mu_s n", "mu_k n",
    "ax fy", "ay fz",
}

# Diagram variables glued with capital letters (e.g. Fman, Fground, Fearth, Fsun, N1, F1)
_DIAGRAM_VARIABLE_PATTERN = re.compile(
    r"^(?:Fsun|Fearth|Fground|Fman|Fext|Fnet|F1|F2|F3|N1|N2|N3|R1|R2|T1|T2|f_man|f_ground|f_sun|f_earth|f_1|f_2)$"
    r"|^[FNTR]_[a-z0-9]+$"
    r"|^[FNTR]\d+$",
    re.IGNORECASE,
)

# Generic words derived from all-caps headings that cannot stand as individual concepts
_GENERIC_HEADING_WORDS: Set[str] = {
    "laws", "motion", "angle", "repose", "newton",
    "note", "notes", "revision", "summary", "chapter", "section",
    "part", "unit", "properties", "types", "download", "app",
    "esaral", "class", "exam", "neet", "jee", "direction", "magnitude",
    "contact", "surfaces", "surface", "value", "values", "body", "block",
    "concept", "concepts", "formula", "formulas", "example", "examples",
    "topic", "topics", "definition", "definitions",
}

# Non-conceptual descriptive phrases or geometric parameters that are not teachable concepts
_NON_CONCEPTUAL_DESCRIPTIVES: Set[str] = {
    "contact surfaces", "contact surface", "maximum value", "minimum value",
    "angle of inclination", "inclination angle", "constant value", "particular value",
    "critical value", "limiting value", "sliding surface", "two contact surfaces",
    "rest of body", "pairs of forces", "action reaction pairs", "external force",
    "area of contact", "terms of components", "circular path", "object in motion",
    "property of inertial mass", "block of mass", "relative to the other body",
    "equal but oppositely force", "action-reaction pairs", "action-reaction pair",
    "action reaction pair", "terms of cartesian components", "cartesian components",
}

# Genitive / descriptive prose expressions describing quantities of objects rather than concept names
_GENITIVE_DESCRIPTIVE_PATTERN = re.compile(
    r"\b(?:product|sum|ratio|magnitude|direction|speed|velocity|acceleration|force|surface|friction|property|value)\s+(?:of|on|between)\s+(?:its|the|each|two|a|an|both)\b",
    re.IGNORECASE
)

# Incomplete truncated phrases that require repair
_TRUNCATED_REPAIR_MAP: Dict[str, str] = {
    "coefficient of kinetic": "Coefficient of Kinetic Friction",
    "coefficient of static": "Coefficient of Static Friction",
    "limiting force of": "Limiting Friction",
    "angle of repose on": "Angle of Repose",
    "net acceleration in": "Net Acceleration",
    "net acceleration in circular": "Net Acceleration in Circular Motion",
    "properties of": "Properties of Friction",
    "laws of": "Laws of Friction",
    "first law": "Newton's First Law",
    "second law": "Newton's Second Law",
    "third law": "Newton's Third Law",
    "oefficient of static friction": "Coefficient of Static Friction",
    "oefficient of kinetic friction": "Coefficient of Kinetic Friction",
    "tal acceleration": "Centripetal Acceleration",
    "centripe tal acceleration": "Centripetal Acceleration",
    "adial acceleration": "Radial Acceleration",
    "called kinetic friction": "Kinetic Friction",
    "called radial acceleration": "Radial Acceleration",
    "called the angle of repose": "Angle of Repose",
    "constant value called kinetic friction": "Kinetic Friction",
    "s laws": "Newton's Laws of Motion",
    "slipiry or relative motion": "Relative Motion",
}

# Finite verbs, auxiliary verbs, and modal verbs indicating clauses/sentences rather than noun phrases
_FINITE_VERBS: Set[str] = {
    "is", "are", "was", "were", "has", "have", "had", "be", "been", "being",
    "do", "does", "did", "can", "could", "will", "would", "shall", "should", "may", "might",
    "states", "stated", "stating", "exert", "exerts", "exerted", "exerting", "slide", "slides", "slid", "sliding",
    "undergo", "undergoes", "underwent", "undergone", "undergoing",
    "lose", "loses", "lost", "losing",
    "carry", "carries", "carried", "carrying",
    "absorb", "absorbs", "absorbed", "absorbing",
    "emit", "emits", "emitted", "emitting",
    "occupy", "occupies", "occupied", "occupying",
    "involve", "involves", "involved", "involving",
    "consist", "consists", "consisted", "consisting",
    "possess", "possesses", "possessed", "possessing",
    "move", "moves", "moving", "moved", "accelerate", "accelerates", "accelerating", "accelerated", "change", "changes",
    "changing", "changed", "begin", "begins", "beginning", "began", "start", "starts", "starting", "started",
    "vary", "varies", "varying", "varied", "act", "acts", "acting", "acted", "remain", "remains", "remaining", "remained",
    "continue", "continues", "continuing", "continued", "decrease", "decreases", "decreasing", "decreased",
    "increase", "increases", "increasing", "increased", "adjust", "adjusts", "adjusting", "adjusted", "give", "gives",
    "giving", "given", "place", "placed", "placing", "places", "keep", "keeps", "keeping", "kept", "show", "shows",
    "showing", "shown", "exist", "exists", "existing", "existed", "contain", "contains", "containing", "contained",
    "describe", "describes", "described", "describing", "apply", "applies", "applied", "applying", "depend", "depends",
    "maintain", "maintains", "maintained", "maintaining", "produce", "produces", "produced", "producing",
    "experience", "experiences", "experienced", "experiencing", "prevent", "prevents", "prevented", "preventing",
    "require", "requires", "required", "requiring", "provide", "provides", "provided", "providing",
    "called", "known", "named", "termed", "defined", "considered", "referred",
    "proportional", "opposing", "relate", "relates", "related", "relating", "study", "studies", "studied", "studying", "use", "uses", "used", "using",
}

# Clause starters and sentential markers
_CLAUSE_STARTERS: Set[str] = {
    "there is", "there are", "no net", "is no", "when", "if", "then", "suppose",
    "whenever", "note that", "in terms", "terms of", "pairs of", "in which",
    "where", "that", "which", "who", "whom", "whose", "because", "while",
}

# Subject-verb, verb-noun, and copular action fragments
_ACTION_FRAGMENT_PATTERNS = [
    re.compile(r"^(?:object|body|block|surface|particle|mass|sun|earth|man|block)\s+(?:exerts?|slides?|moves?|accelerates?|starts?|acts?|remains?|varies|placed|is|was|has|exists?)", re.IGNORECASE),
    re.compile(r"^(?:force|force\s+of)\s+(?:exerted|acting|applied|opposing)", re.IGNORECASE),
    re.compile(r"^(?:is|are|was|were|has|have|s is|is a|are a)\s+(?:a\s+)?constant", re.IGNORECASE),
    re.compile(r"^(?:equal\s+and\s+opposite|direct\s+opposite|equal\s+but\s+oppositely)$", re.IGNORECASE),
    re.compile(r"\b(?:exerts?|slides?|varies|sliding|acted|acting|states?|remains?|continues?|exists?)\b", re.IGNORECASE),
    re.compile(r"\b(?:perpendicular|parallel|proportional|relative)\s+to\b", re.IGNORECASE),
    re.compile(r"\b(?:bounded\s+between|bounded\s+by|spontaneous\s+transfer|done\s+by|done\s+or|dissipates?\b|counterpart\s+of|analogue\s+of)\b", re.IGNORECASE),
    re.compile(r"^(?:next|previous|another|certain|various|several)\s+(?:concept|topic|formula|example)\b", re.IGNORECASE),
]

# Trailing adjectives / conjunctions / prepositions indicating incomplete truncation
_INVALID_TRAILING_TOKENS: Set[str] = {
    "kinetic", "static", "limiting", "opposite", "inclined", "constant",
    "direct", "relative", "maximum", "minimum", "sliding", "moving",
    "of", "in", "on", "at", "to", "for", "by", "with", "between",
    "and", "or", "nor", "but", "so", "than", "as", "is", "are", "was",
}

# Leading function words that should never begin an academic concept
_INVALID_LEADING_TOKENS: Set[str] = {
    "of", "in", "on", "at", "by", "with", "between", "along", "from", "to", "into",
    "and", "or", "but", "nor", "if", "then", "when", "where", "while", "because",
    "thus", "so", "as", "than", "there", "here", "just", "only", "well",
    "oppositely", "directly", "it", "its", "they", "them", "their", "we", "our",
    "you", "your", "he", "she", "his", "her", "that", "which", "who", "whom",
    "this", "these", "those", "when", "whenever", "suppose", "note",
    "also", "always", "down", "up", "under", "above", "below", "across", "through", "along",
    "called", "known", "named", "value", "constant", "opposite", "opposing",
    "magnitude", "direction", "product", "sum", "relation", "inclination",
    "oefficient", "tal", "adial", "mal",
    "next", "previous", "another", "certain", "various", "several",
    "bounded", "calculated", "derived", "obtained", "formed", "composed",
    "passing", "given", "approaches", "yields", "remains", "condenses",
    "decreases", "increases", "perpendicular", "parallel",
    "proportional", "spontaneous", "done", "like",
}

# Leading determiners to trim cleanly
_LEADING_TRIM_WORDS: Set[str] = {
    "the", "a", "an", "such", "some", "any", "each", "every",
}

# Academic concept canonical alias map (for Laws of Motion & Classical Mechanics)
_KNOWN_ACADEMIC_ALIASES: Dict[str, str] = {
    "first law": "Newton's First Law",
    "newtons first law": "Newton's First Law",
    "newton's first law of motion": "Newton's First Law",
    "first law of motion": "Newton's First Law",
    "law of inertia": "Newton's First Law",
    "second law": "Newton's Second Law",
    "newtons second law": "Newton's Second Law",
    "newton's second law of motion": "Newton's Second Law",
    "second law of motion": "Newton's Second Law",
    "third law": "Newton's Third Law",
    "newtons third law": "Newton's Third Law",
    "newton's third law of motion": "Newton's Third Law",
    "third law of motion": "Newton's Third Law",
    "newtons laws": "Newton's Laws of Motion",
    "newton's laws": "Newton's Laws of Motion",
    "laws of motion": "Newton's Laws of Motion",
    "force of friction": "Friction",
    "frictional force": "Friction",
    "friction force": "Friction",
    "static friction force": "Static Friction",
    "static frictions": "Static Friction",
    "kinetic friction force": "Kinetic Friction",
    "limiting force of friction": "Limiting Friction",
    "maximum static friction": "Limiting Friction",
    "maximum static friction force": "Limiting Friction",
    "radial acceleration": "Centripetal Acceleration",
    "net acceleration in circular motion": "Net Acceleration",
    "angle of friction": "Angle of Repose",
    "normal reaction": "Normal Force",
    "normal reaction force": "Normal Force",
    "normal response": "Normal Force",
    "angular speed": "Angular Velocity",
    "pi-bond": "Pi Bond",
    "pi bond": "Pi Bond",
    "vsepr": "VSEPR Theory",
    "vsepr theory": "VSEPR Theory",
    "valence shell electron pair repulsion": "VSEPR Theory",
    "valence shell electron pair repulsion theory": "VSEPR Theory",
    "mot": "Molecular Orbital Theory",
    "vbt": "Valence Bond Theory",
    "cft": "Crystal Field Theory",
    "fbd": "Free Body Diagram",
}

# Substantive valid single-word concepts that are completely legitimate in STEM
_LEGITIMATE_SINGLE_WORD_CONCEPTS: Set[str] = {
    # Physics & Mechanics & Thermodynamics
    "friction", "momentum", "mass", "inertia",
    "torque", "equilibrium", "work", "energy", "power", "pressure", "temperature",
    "heat", "charge", "current", "flux", "potential", "capacitance", "inductance",
    "resistance", "dipole", "gravitation", "impulse", "collision", "collisions",
    # Chemistry & Physical Chemistry
    "enthalpy", "entropy", "hybridization", "electronegativity", "catalyst", "isomerism",
    "stoichiometry", "thermodynamics", "electrochemistry", "metallurgy",
    "ligand", "ligands", "chelate", "chelates", "isomer", "isomers", "alkane", "alkanes",
    "alkene", "alkenes", "alkyne", "alkynes", "cation", "cations", "anion", "anions",
    "radical", "radicals", "resonance", "titration",
    # Biology & Cell Biology
    "mitochondria", "mitochondrion", "ribosome", "ribosomes", "lysosome", "lysosomes",
    "nucleus", "chromatin", "nucleolus", "prokaryote", "eukaryote", "organelle", "organelles",
    "cytoplasm", "chloroplast", "chloroplasts", "vacuole", "vacuoles",
    "mitosis", "meiosis", "prophase", "metaphase", "anaphase", "telophase",
    "interphase", "cytokinesis", "kinetochore", "centromere", "centrosome",
    "centriole", "chiasma", "chiasmata", "synapsis", "bivalent", "gamete", "gametes", "zygote",
    # Mathematics & Geometry
    "eccentricity", "parabola", "ellipse", "hyperbola", "asymptote", "asymptotes", "focus", "directrix", "tangent",
    # Mathematics & Combinatorics & Algebra
    "permutation", "permutations", "combination", "combinations", "factorial",
    "derangement", "derangements", "divisor", "divisors", "vector", "vectors", "scalar", "scalars",
    # Mathematics & Calculus
    "calculus", "derivative", "integral", "limit", "matrix", "matrices",
    "differentiation", "integration", "algebra", "geometry", "statistics",
    "determinant", "determinants",
    "probability", "trigonometry", "continuity", "differentiability",
    # Computing & Foundations
    "algorithm", "network", "database", "function",
}

# Substantive valid academic head noun vocabulary
_SUBSTANTIVE_HEAD_NOUNS: Set[str] = {
    # Physical sciences & General Academic STEM
    "theory", "theories", "rule", "rules", "law", "laws", "theorems",
    "line", "lines", "form", "forms", "cycle", "cycles", "effect", "effects",
    "diagram", "diagrams", "number", "numbers", "motion", "friction", "force", "forces", "acceleration", "velocity", "moment", "bonding", "parts", "reaction", "mass", "inertia", "inertias",
    "momentum", "energy", "work", "power", "torque",
    "repose", "theorem", "principle", "principles", "method", "methods",
    "system", "systems", "constant", "coefficient", "coefficients", "property",
    "properties", "equilibrium", "density", "pressure", "temperature", "volume",
    "charge", "current", "field", "potential", "resistance", "capacitance",
    "inductance", "flux", "frequency", "wavelength", "amplitude", "oscillation",
    "wave", "waves", "collision", "impulse", "plane", "incline", "particle",
    "body", "model", "gas", "gases", "process", "processes",
    # Chemical sciences
    "bond", "bonds", "enthalpy", "fraction", "fractions", "substitution", "substitutions", "gradient", "gradients", "distribution", "distributions", "variable", "variables", "quantity", "quantities", "transformation", "transformations", "interaction", "interactions", "product", "products", "pair", "pairs", "orbital", "orbitals", "hybridization", "geometry",
    "acid", "acids", "base", "bases", "solution", "solutions", "compound", "compounds",
    "molecule", "molecules", "atom", "atoms", "ion", "ions", "entropy", "kinetics",
    "order", "reaction", "reactions", "element", "elements",
    # Biological sciences
    "cell", "cells", "membrane", "membranes", "organelle", "organelles",
    "reticulum", "apparatus", "mitochondrion", "mitochondria", "ribosome", "ribosomes",
    "lysosome", "lysosomes", "nucleus", "chromatin", "chromosome", "chromosomes",
    "nucleolus", "protein", "proteins", "enzyme", "enzymes", "tissue", "tissues",
    "division", "divisions", "phase", "phases", "fiber", "fibers", "plate", "plates",
    "furrow", "furrows", "spindle", "spindles",
    # Chemical sciences additions
    "ligand", "ligands", "complex", "complexes", "sphere", "spheres", "reagent", "reagents",
    "titration", "titrations", "isomer", "isomers",
    # Mathematical sciences
    "integral", "derivative", "limit", "series", "sequence", "equation", "equations",
    "function", "functions", "relation", "relations",
    "set", "sets", "matrix", "matrices", "conic", "conics", "parabola", "ellipse",
    "hyperbola", "asymptote", "asymptotes", "section", "sections", "slope", "intercept",
    "continuity", "differentiability", "curve", "curves", "locus", "focus", "directrix",
    "permutation", "permutations", "combination", "combinations", "factorial", "factorials",
    "derangement", "derangements", "determinant", "determinants", "divisor", "divisors",
    # Structural & Informational
    "complexity", "programming", "notation", "traversal", "search", "sorting",
    "algorithm", "tree", "graph", "network", "structure", "structures",
    "database", "databases", "entity", "entities", "query", "queries", "learning", "state", "states",
}


class SemanticConceptValidator:
    """
    Validates and classifies candidate educational concepts, rejecting extraction artifacts
    and preserving legitimate curriculum concepts with their aliases and evidence.
    """

    def __init__(self):
        pass

    @staticmethod
    def clean_text_formatting(text: str) -> str:
        """
        Standardizes unicode apostrophes, dashes, math symbols, and whitespace.
        """
        if not text:
            return ""
        # Normalize NFKC
        text = unicodedata.normalize("NFKC", text)
        # Apostrophes & single quotation marks -> standard ASCII '
        text = re.sub(r"[\u2018\u2019\u201b\u02bc\u2032`´]", "'", text)
        # Middle dot or bullet used as apostrophe (e.g. Newton·s -> Newton's)
        text = re.sub(r"(?<=[A-Za-z])[\u00b7•·](?=[A-Za-z])", "'", text)
        # Hyphens & dashes -> standard ASCII -
        text = re.sub(r"[\u2010\u2011\u2012\u2013\u2014\u2212]", "-", text)
        # Greek symbol font mappings (Symbol font ASCII encodings in PDF streams)
        text = (
            text.replace("\uf070", "pi")
            .replace("\uf061", "alpha")
            .replace("\uf062", "beta")
            .replace("\uf067", "gamma")
            .replace("\uf064", "delta")
            .replace("\uf077", "omega")
            .replace("\uf06c", "lambda")
            .replace("\uf073", "sigma")
            .replace("\uf06d", "mu")
            .replace("\uf071", "theta")
            .replace("\uf066", "phi")
            .replace("\uf02d", "-")
        )
        # De-hyphenate and fix broken line-wraps across lines
        text = re.sub(r"([A-Za-z]+)-\s*\n\s*([A-Za-z]+)", r"\1\2", text)
        text = re.sub(r"\b([A-Za-z])\s*\n\s*([a-z]{3,})\b", r"\1\2", text)
        # Collapse horizontal whitespace, preserving newlines
        text = re.sub(r"[^\S\r\n]+", " ", text)
        # Collapse excessive blank lines
        text = re.sub(r"\n\s*\n+", "\n\n", text).strip()
        return text

    @classmethod
    def normalize_concept_name(cls, term: str) -> str:
        """
        Transforms candidate string into canonical title-cased academic concept name.
        Preserves standard possessives (e.g. Newton's) and internal lowercase prepositions.
        """
        clean = cls.clean_text_formatting(term)
        words = clean.split()
        if not words:
            return ""

        # Trim leading function words
        while words and words[0].lower() in _LEADING_TRIM_WORDS:
            words = words[1:]
        if not words:
            return ""

        # Re-title case words
        title_words = []
        lower_connectives = {"of", "in", "and", "or", "for", "to", "at", "by", "on", "a", "an", "the"}
        for i, w in enumerate(words):
            low = w.lower()
            if i > 0 and low in lower_connectives and i < len(words) - 1:
                title_words.append(low)
            elif "'" in w:
                parts = w.split("'", 1)
                title_words.append(f"{parts[0].capitalize()}'{parts[1].lower()}")
            elif w.isupper() and len(w) <= 5:
                # Keep legitimate short acronyms uppercase (e.g. JEE, EKR, DAG)
                title_words.append(w)
            else:
                title_words.append(w.capitalize())

        return " ".join(title_words)

    @classmethod
    def validate_candidate(
        cls,
        raw_term: str,
        document_context: Optional[str] = None,
        active_concepts: Optional[Set[str]] = None,
    ) -> Tuple[bool, ConceptValidationOutcome, str, Optional[str]]:
        """
        Validates a candidate concept phrase.

        Returns:
            (is_valid, outcome, final_concept_name_or_reason, optional_canonical_target)
        """
        clean = cls.clean_text_formatting(raw_term)
        if not clean or len(clean) < 2:
            return False, ConceptValidationOutcome.REJECTED_NOISE, RejectionCategory.OCR_ARTIFACT.value, None

        low = clean.lower()

        # 1. Check known equation fragments & math tokens
        if low in _EQUATION_FRAGMENTS:
            return False, ConceptValidationOutcome.REJECTED_NOISE, RejectionCategory.EQUATION_FRAGMENT.value, None
        if any(math_pat in low for math_pat in ("mg sin", "mg cos", "tan phi", "sigma f", "sigma fx", "sigma fy", "sigma fz")):
            return False, ConceptValidationOutcome.REJECTED_NOISE, RejectionCategory.EQUATION_FRAGMENT.value, None
        if re.search(r"[=<>+*/^]", clean):
            return False, ConceptValidationOutcome.REJECTED_NOISE, RejectionCategory.EQUATION_FRAGMENT.value, None

        # 2. Check diagram variables (Fman, Fground, Fearth, Fsun, N1, ax Fy)
        if _DIAGRAM_VARIABLE_PATTERN.match(clean) or re.search(r"\b[A-Za-z]\s+[FNTR][a-z0-9]?\b", clean):
            return False, ConceptValidationOutcome.REJECTED_NOISE, RejectionCategory.DIAGRAM_VARIABLE.value, None

        # Check trailing variable symbols (e.g. "acceleration alpha", "critical angle phi")
        m_var = re.search(r"^(.*?)\s+(?:alpha|beta|gamma|theta|phi|omega|mu|nu|rho|tau|sigma|delta|epsilon|[a-z])$", clean, re.IGNORECASE)
        if m_var:
            base = m_var.group(1).strip()
            if len(base.split()) >= 2:
                base_val, base_out, base_name, base_alias = cls.validate_candidate(base, document_context, active_concepts)
                if base_val:
                    return True, ConceptValidationOutcome.REPAIRED_CONCEPT, base_name, base_alias
            return False, ConceptValidationOutcome.REJECTED_NOISE, RejectionCategory.EQUATION_FRAGMENT.value, None

        # 3. Check truncated phrases with known repairs
        if low in _TRUNCATED_REPAIR_MAP:
            repaired = _TRUNCATED_REPAIR_MAP[low]
            if low in ("first law", "second law", "third law"):
                return True, ConceptValidationOutcome.ALIAS_VARIANT, cls.normalize_concept_name(clean), repaired
            return True, ConceptValidationOutcome.REPAIRED_CONCEPT, repaired, None

        # 4. Check action verbs and sentence fragments
        for pat in _ACTION_FRAGMENT_PATTERNS:
            if pat.search(low):
                return False, ConceptValidationOutcome.REJECTED_NOISE, RejectionCategory.ACTION_VERB_PHRASE.value, None

        # 5. Check finite verbs inside phrase
        words = [w for w in re.split(r"[\s\-]+", clean) if w]
        if any(w.lower() in _FINITE_VERBS for w in words):
            return False, ConceptValidationOutcome.REJECTED_NOISE, RejectionCategory.ACTION_VERB_PHRASE.value, None

        # 6. Check clause starters
        if any(low.startswith(cs) for cs in _CLAUSE_STARTERS):
            return False, ConceptValidationOutcome.REJECTED_NOISE, RejectionCategory.SENTENCE_FRAGMENT.value, None

        # 7. Check non-conceptual descriptive phrases, genitive relations, and coordinate conjoined clauses
        if low in _NON_CONCEPTUAL_DESCRIPTIVES:
            return False, ConceptValidationOutcome.REJECTED_NOISE, RejectionCategory.NON_CONCEPTUAL_DESCRIPTIVE.value, None
        if _GENITIVE_DESCRIPTIVE_PATTERN.search(low):
            return False, ConceptValidationOutcome.REJECTED_NOISE, RejectionCategory.NON_CONCEPTUAL_DESCRIPTIVE.value, None
        # Reject phrases conjoining two separate entities with 'and the', 'and its', 'and a'
        if re.search(r"\b(?:and|with)\s+(?:the|its|a|an)\b", low):
            return False, ConceptValidationOutcome.REJECTED_NOISE, RejectionCategory.NON_CONCEPTUAL_DESCRIPTIVE.value, None
        # Reject entities embedded in subject particles like 'object in motion' or 'particle in non-uniform'
        if re.search(r"^(?:object|body|particle)\s+in\b", low):
            return False, ConceptValidationOutcome.REJECTED_NOISE, RejectionCategory.NON_CONCEPTUAL_DESCRIPTIVE.value, None

        # 8. Check invalid leading tokens
        if words and words[0].lower() in _INVALID_LEADING_TOKENS:
            return False, ConceptValidationOutcome.REJECTED_NOISE, RejectionCategory.INCOMPLETE_PHRASE.value, None

        # 9. Single-word concept validation: only legitimate domain STEM concepts are accepted standalone
        if len(words) == 1:
            w_low = words[0].lower()
            if w_low in _KNOWN_ACADEMIC_ALIASES:
                target = _KNOWN_ACADEMIC_ALIASES[w_low]
                return True, ConceptValidationOutcome.ALIAS_VARIANT, cls.normalize_concept_name(clean), target
            if w_low in _LEGITIMATE_SINGLE_WORD_CONCEPTS:
                return True, ConceptValidationOutcome.VALID_CONCEPT, cls.normalize_concept_name(clean), None
            return False, ConceptValidationOutcome.REJECTED_NOISE, RejectionCategory.GENERIC_WORD.value, None

        # 10. Check trailing invalid tokens (incomplete phrases)
        if words and words[-1].lower() in _INVALID_TRAILING_TOKENS:
            # Incomplete dangling phrase (e.g. ending in preposition or incomplete modifier)
            return False, ConceptValidationOutcome.REJECTED_NOISE, RejectionCategory.INCOMPLETE_PHRASE.value, None

        # 11. Check known aliases and subtopic mappings
        norm_name = cls.normalize_concept_name(clean)
        norm_low = norm_name.lower()
        if norm_low in _KNOWN_ACADEMIC_ALIASES:
            canonical_parent = _KNOWN_ACADEMIC_ALIASES[norm_low]
            if norm_name != canonical_parent:
                return True, ConceptValidationOutcome.ALIAS_VARIANT, norm_name, canonical_parent
            return True, ConceptValidationOutcome.VALID_CONCEPT, canonical_parent, None

        # 12. Special handling for 'Net Force' and recognized compound verbal/particle terms
        if norm_low == "net force":
            return True, ConceptValidationOutcome.VALID_CONCEPT, "Net Force", None
        if norm_low in {"crossing over", "crossover"}:
            return True, ConceptValidationOutcome.VALID_CONCEPT, cls.normalize_concept_name(clean), None

        # 13. Substantive head noun verification:
        # A valid multi-word STEM concept must end with a substantive head noun
        last_word = words[-1].lower() if words else ""
        if last_word in _SUBSTANTIVE_HEAD_NOUNS:
            if 2 <= len(words) <= 6:
                return True, ConceptValidationOutcome.VALID_CONCEPT, norm_name, None

        return False, ConceptValidationOutcome.REJECTED_NOISE, RejectionCategory.NON_CONCEPTUAL_DESCRIPTIVE.value, None

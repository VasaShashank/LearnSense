"""
Text normalization for the canonical curriculum module (Person 2).

Normalization has two *deliberately different* levels, because they have different
safety requirements.  Conflating them is how math notation and chemical formulae
get destroyed, so the split is explicit here:

``normalize_text``
    Storage level.  Unicode NFC plus whitespace cleanup only.  Case, Greek
    letters, super/subscripts, operators and formulae survive unchanged, so a
    stored canonical name, alias or evidence excerpt is never damaged.

``normalize_term``
    Comparison level.  Used to build *match keys* for concept names and aliases.
    Typographic quotes and dashes are unified, apostrophes and sentence
    punctuation become separators, and case is folded.  Notation characters
    (``/ = + ^ _ °`` and super/subscripts, Greek letters, math operators) are
    explicitly *protected* so ``m/s²`` is not mangled into ``m/s2``.

``normalize_formula``
    Storage level for formulae.  NFC and whitespace cleanup, but never casefold
    and never punctuation removal, because ``CO`` and ``Co`` are different
    chemical symbols and ``x_i`` is not ``x i``.

Matching keys are therefore ``normalize_term`` output; everything that is stored
or shown to a teacher is ``normalize_text`` / ``normalize_formula`` output.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Dict, List, Sequence, Tuple

# Typographic variants that should compare equal to their ASCII counterpart.
# Only *typographic* characters are folded here; notation is never touched.
_TYPOGRAPHIC_MAP: Dict[str, str] = {
    "\u2018": "'",  # ‘
    "\u2019": "'",  # ’
    "\u201a": "'",
    "\u201b": "'",
    "\u2032": "'",  # ′ prime
    "\u00b4": "'",  # ´
    "\u201c": '"',
    "\u201d": '"',
    "\u201e": '"',
    "\u201f": '"',
    "\u2033": '"',
    "\u2010": "-",  # hyphen
    "\u2011": "-",  # non-breaking hyphen
    "\u2012": "-",  # figure dash
    "\u2013": "-",  # en dash
    "\u2014": "-",  # em dash
    "\u2015": "-",  # horizontal bar
    "\u2212": "-",  # minus sign: PDF-extracted physics text writes "velocity-time"
    "\u00a0": " ",  # no-break space
    "\u2007": " ",
    "\u2009": " ",  # thin space
    "\u202f": " ",  # narrow no-break space
    "\u200b": "",  # zero width space
    "\ufeff": "",  # BOM
    "\u00ad": "",  # soft hyphen
    "\u2026": "...",  # ellipsis
}

# Apostrophes are removed outright so "Newton's" and "Newtons" compare equal.
_APOSTROPHES = {"'", "`", "\u02bc"}

# Sentence / clause punctuation that becomes a separator in a *term key*.
# Notation characters are deliberately absent: / = + ^ _ ° √ ∫ ± ≈ ≤ ≥ · × ÷
# together with super/subscripts and Greek letters must survive.
_SEPARATORS = set("-,;:()[]{}!?<>\"|@#~")

_SEPARATOR_CLASS = "".join(re.escape(ch) for ch in sorted(_SEPARATORS))
_SEPARATOR_RE = re.compile(f"[{_SEPARATOR_CLASS}]+")


def normalize_text(text: str) -> str:
    """Storage-level normalization: NFC + whitespace collapse.  Never casefolds."""
    if not text:
        return ""
    folded = text.translate(
        str.maketrans({k: v for k, v in _TYPOGRAPHIC_MAP.items() if k in "\u200b\ufeff\u00ad"})
    )
    return re.sub(r"\s+", " ", unicodedata.normalize("NFC", folded)).strip()


def normalize_formula(text: str) -> str:
    """
    Storage-level normalization for formulae.

    Case is significant in chemistry (``CO`` carbon monoxide vs ``Co`` cobalt) and
    subscripts are significant in notation (``x_1`` vs ``x1``), so only whitespace
    and the invisible characters are cleaned up.
    """
    if not text:
        return ""
    cleaned = text.translate(str.maketrans({"\u200b": "", "\ufeff": "", "\u00ad": ""}))
    return re.sub(r"\s+", " ", unicodedata.normalize("NFC", cleaned)).strip()


def normalize_term(text: str) -> str:
    """
    Comparison-level normalization producing a *match key*.

    Steps, in order:

    1. Unicode NFC (not NFKC: NFKC rewrites ``²`` to ``2`` and ``ﬁ`` to ``fi``,
       which damages notation).
    2. Typographic quotes and dashes folded to ASCII.
    3. Apostrophes removed (``Newton's`` -> ``Newtons``).
    4. Sentence punctuation replaced by a single space; notation characters kept.
    5. Whitespace collapsed, string stripped.
    6. ``casefold`` for case-insensitive terminology matching.
    """
    if not text:
        return ""
    text = unicodedata.normalize("NFC", text)
    text = text.translate(str.maketrans(_TYPOGRAPHIC_MAP))
    for apostrophe in _APOSTROPHES:
        text = text.replace(apostrophe, "")
    text = _SEPARATOR_RE.sub(" ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text.casefold()


#: Backwards-friendly alias: match keys are the normalized term form.
normalize_key = normalize_term

_STOPWORDS = {
    "a", "an", "the", "of", "in", "on", "to", "and", "or", "for", "is", "are",
    "be", "by", "with", "at", "from", "that", "this", "it", "as", "its",
}

# Sentence boundary: a terminator followed by whitespace, or a hard newline.
# Decimal numbers ("3.14") never match because no whitespace follows the dot.
_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+|\n+")

# Characters that mark a term as a notation variant rather than plain wording.
_NOTATION_CHARS = set("=+-/^_°√∫∑∏∞±≈≠≤≥·×÷<>[]{}()0123456789αβγδεζηθικλμνξπρστυφχψωΔΩΣΠΦΨ")


def split_sentences(text: str) -> List[str]:
    """
    Deterministic sentence splitter.

    Known limitation: an abbreviation ending in a dot followed by a space
    ("e.g. the") splits early.  This is accepted because the mapper matches
    whole terms inside each fragment either way, and a deterministic simple rule
    beats an unpinned heuristic.
    """
    if not text:
        return []
    parts = [part.strip() for part in _SENTENCE_SPLIT_RE.split(text)]
    return [part for part in parts if part]


def tokenize(key: str) -> List[str]:
    """Normalized key -> content tokens (stopwords removed), order preserved."""
    return [token for token in (key or "").split() if token and token not in _STOPWORDS]


def jaccard_similarity(left: Sequence[str], right: Sequence[str]) -> float:
    """Jaccard similarity over token multisets-as-sets.  Empty vs empty is 0.0."""
    a, b = set(left), set(right)
    if not a or not b:
        return 0.0
    return len(a & b) / float(len(a | b))


def is_notation_variant(key: str) -> bool:
    """True when a key contains digits or math/chemistry notation characters."""
    return any(char in _NOTATION_CHARS for char in key)


_TERM_BOUNDARY_RE_CACHE: Dict[str, re.Pattern] = {}


def term_pattern(surface_key: str) -> re.Pattern:
    """Word-boundary aware regex for a normalized surface key."""
    pattern = _TERM_BOUNDARY_RE_CACHE.get(surface_key)
    if pattern is None:
        pattern = re.compile(r"(?<!\w)" + re.escape(surface_key) + r"(?!\w)")
        _TERM_BOUNDARY_RE_CACHE[surface_key] = pattern
    return pattern


def find_term_occurrences(haystack_key: str, surface_key: str) -> List[Tuple[int, int]]:
    """
    Locate ``surface_key`` inside a normalized ``haystack_key``.

    Both arguments must already be ``normalize_term`` output, so the two strings
    are normalized identically and offsets are meaningful for the *key*, not for
    the original text.  Callers match per sentence and keep the original
    sentence as the excerpt.
    """
    if not haystack_key or not surface_key:
        return []
    return [match.span() for match in term_pattern(surface_key).finditer(haystack_key)]


def contains_term(haystack_key: str, surface_key: str) -> bool:
    """True when the surface key occurs on term boundaries in the haystack key."""
    return bool(find_term_occurrences(haystack_key, surface_key))


def strip_notation(key: str) -> str:
    """Drop notation characters, leaving the wording of a term (for fuzzy rules)."""
    return re.sub(r"[^\w\s]", " ", key, flags=re.UNICODE).strip()


_SUPERSCRIPT_DIGITS = str.maketrans("\u2070\u00b9\u00b2\u00b3\u2074\u2075\u2076\u2077\u2078\u2079", "0123456789")
_SUBSCRIPT_DIGITS = str.maketrans("\u2080\u2081\u2082\u2083\u2084\u2085\u2086\u2087\u2088\u2089", "0123456789")


def fold_superscripts(text: str) -> str:
    """
    Rewrite super/subscript digits to ASCII for *comparison only*.

    ``m/s²`` and ``m/s^2`` and ``m/s2`` denote the same thing to a reader, so a
    notation-variant match has to be able to see that.  Stored text is never
    rewritten this way.
    """
    if not text:
        return ""
    return text.translate(_SUPERSCRIPT_DIGITS).translate(_SUBSCRIPT_DIGITS)

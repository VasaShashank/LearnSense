"""
Normalization rules (Person 2).

These tests pin down the two-level split the module documents: storage level
(``normalize_text`` / ``normalize_formula``) never damages case, notation or
formulae, while comparison level (``normalize_term``) folds typographic noise
only.  Math/chemical notation surviving normalization is the property most
likely to regress silently, so it is checked explicitly.
"""

from __future__ import annotations

from curriculum.normalization import (
    contains_term,
    find_term_occurrences,
    fold_superscripts,
    is_notation_variant,
    jaccard_similarity,
    normalize_formula,
    normalize_term,
    normalize_text,
    split_sentences,
    strip_notation,
    term_pattern,
    tokenize,
)


class TestComparisonLevel:
    def test_case_and_whitespace_are_folded(self):
        assert normalize_term("  Velocity   Graph  ") == "velocity graph"

    def test_typographic_dashes_become_separators(self):
        # hyphen, en dash and minus sign must all produce the same match key.
        assert normalize_term("Velocity-Time Graph") == "velocity time graph"
        assert normalize_term("Velocity\u2013Time Graph") == "velocity time graph"
        assert normalize_term("Velocity\u2212Time Graph") == "velocity time graph"

    def test_apostrophes_and_quotes_are_folded(self):
        assert normalize_term("Newton's Second Law") == "newtons second law"
        assert normalize_term("\u201cOhm\u2019s Law\u201d") == "ohms law"

    def test_math_notation_is_protected(self):
        # The whole point of the split: comparison must not mangle notation.
        assert normalize_term("m/s\u00b2") == "m/s\u00b2"
        assert normalize_term("log_b(x)") == "log_b x"
        assert normalize_term("CaCO_3") == "caco_3"

    def test_is_idempotent(self):
        once = normalize_term("Velocity-Time Graph")
        assert normalize_term(once) == once


class TestStorageLevel:
    def test_normalize_text_keeps_case(self):
        assert normalize_text("  Newton's   Second Law ") == "Newton's Second Law"

    def test_normalize_formula_keeps_case_and_punctuation(self):
        assert normalize_formula("H2SO4") == "H2SO4"
        assert normalize_formula("h2so4") == "h2so4"
        assert normalize_formula("CaCO_3") == "CaCO_3"

    def test_formula_case_is_never_folded(self):
        # Case-folding a formula would silently turn one chemical into another.
        assert normalize_formula("CO") != normalize_formula("Co")


class TestSentenceAndTokenHelpers:
    def test_split_sentences_keeps_decimals_intact(self):
        text = "One sentence. Two here! Three? 4.5 is a number."
        assert split_sentences(text) == [
            "One sentence.",
            "Two here!",
            "Three?",
            "4.5 is a number.",
        ]

    def test_tokenize_takes_an_already_normalized_key(self):
        # tokenize() documents its input as normalize_term output: it only drops
        # stopwords and never casefolds or splits punctuation itself.
        key = normalize_term("Velocity-Time Graph")
        assert tokenize(key) == ["velocity", "time", "graph"]
        assert tokenize("Velocity-Time Graph") == ["Velocity-Time", "Graph"]

    def test_jaccard_is_symmetric_and_reflexive(self):
        assert jaccard_similarity("logarithm", "logarithm") == 1.0
        assert jaccard_similarity("a b c", "b c d") == jaccard_similarity("b c d", "a b c")


class TestTermSearch:
    def test_contains_term_respects_word_boundaries(self):
        assert contains_term(normalize_term("the speed is"), normalize_term("speed")) is True
        # "speed" inside "speediness" is not the term.
        assert contains_term(normalize_term("speediness"), normalize_term("speed")) is False

    def test_contains_term_finds_multi_word_phrases(self):
        assert contains_term(
            normalize_term("a v-t graph"), normalize_term("v t graph")
        ) is True

    def test_find_term_occurrences_returns_positions(self):
        occurrences = find_term_occurrences("a v t graph here", "v t graph")
        assert occurrences == [(2, 11)]

    def test_term_pattern_is_boundary_anchored(self):
        pattern = term_pattern("v t graph")
        assert pattern.search("a v t graph")
        assert pattern.search("v t graphs") is None


class TestNotation:
    def test_is_notation_variant_recognises_symbols(self):
        assert is_notation_variant(normalize_term("m/s\u00b2")) is True
        assert is_notation_variant(normalize_term("velocity")) is False

    def test_strip_notation_keeps_the_words(self):
        stripped = strip_notation(normalize_term("m/s\u00b2"))
        assert "/" not in stripped
        assert stripped.strip() != ""

    def test_fold_superscripts(self):
        assert fold_superscripts("x\u00b2") == "x2"

    def test_determinism_across_calls(self):
        samples = ["Velocity-Time Graph", "m/s\u00b2", "Newton's Law", "log_b(x)"]
        first = [normalize_term(sample) for sample in samples]
        second = [normalize_term(sample) for sample in reversed(samples)][::-1]
        assert first == second

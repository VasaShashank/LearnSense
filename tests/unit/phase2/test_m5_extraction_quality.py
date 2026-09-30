"""Unit tests for extraction-quality hardening.

- Stage 5 merges singular/plural variants of the same term instead of
  emitting duplicate concepts ("Derivative" + "Derivatives").
- Topic labels rank by evidence and stay short for large buckets.
"""

from phase2.models import ConceptMention, TextSpan
from phase2.pipeline.stage1_normalize import NormalizedDocumentContext
from phase2.pipeline.stage4_candidates import Stage4ExtractionResult
from phase2.pipeline.stage5_resolution import _fold_plural, run_stage5_entity_resolution


class _NormStub:
    doc_id = "test_doc"

    @staticmethod
    def normalize_text_key(text: str) -> str:
        return NormalizedDocumentContext.normalize_text_key(text)


def _mention(surface: str, idx: int) -> ConceptMention:
    return ConceptMention(
        mention_id=f"m_{idx}",
        concept_id="",
        block_id="b1",
        span=TextSpan(start=0, end=len(surface)),
        surface_form=surface,
    )


def _candidates(*surfaces: str) -> Stage4ExtractionResult:
    res = Stage4ExtractionResult()
    res.mentions = [_mention(s, i) for i, s in enumerate(surfaces)]
    return res


def test_fold_plural_conservative():
    assert _fold_plural("derivatives") == "derivative"
    assert _fold_plural("chain rule derivatives") == "chain rule derivative"
    assert _fold_plural("binary trees") == "binary tree"
    # Never mangled: short tokens, non-alpha tails, calculus-like words.
    assert _fold_plural("calculus") == "calculus"
    assert _fold_plural("news") == "news"
    assert _fold_plural("class") == "class"
    assert _fold_plural("gas") == "gas"
    assert _fold_plural("chain rule") == "chain rule"


def test_stage5_merges_plural_variants():
    candidates = _candidates("Derivative", "Derivative", "Derivative", "Derivatives")
    concepts, _ = run_stage5_entity_resolution(_NormStub(), candidates)
    assert len(concepts) == 1
    assert concepts[0].canonical_name == "Derivative"
    assert len(concepts[0].mention_ids) == 4


def test_stage5_keeps_distinct_terms():
    candidates = _candidates("Limits", "Derivatives", "Chain Rule")
    concepts, _ = run_stage5_entity_resolution(_NormStub(), candidates)
    names = sorted(c.canonical_name for c in concepts)
    assert names == ["Chain Rule", "Derivatives", "Limits"]


def test_stage5_canonical_is_most_frequent_surface():
    candidates = _candidates("derivative", "Derivative", "DERIVATIVE")
    concepts, _ = run_stage5_entity_resolution(_NormStub(), candidates)
    assert len(concepts) == 1
    # "derivative" seen first; all three tie at 1 mention each.
    assert concepts[0].canonical_name == "derivative"

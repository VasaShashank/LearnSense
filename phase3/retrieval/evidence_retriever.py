"""
Source Evidence Retrieval for the LearnSense learning runtime.

Everything LearnSense teaches is generated from the learner's own uploaded material.
That contract is only enforceable if the runtime can *find* the relevant material for a
concept, a skill, a formula or a learning objective and hand the exact passages to the
LLM together with their page/section coordinates.

This module provides that retrieval layer. It indexes:

* every semantic text block of the Phase 1 ``StructuredDocument`` (with page + section), and
* every Phase 2 ``Evidence`` record (spans, kinds and confidence levels),

and scores them with a BM25 ranking function against a concept-derived query. Retrieved
chunks are what the question/content/tutor generators are grounded in; each carries its
provenance so generated artifacts can cite real locations instead of inventing them.
"""

from __future__ import annotations

import math
import re
import unicodedata
from collections import Counter
from typing import Any, Dict, Iterable, List, Optional, Sequence

from pydantic import BaseModel, Field

from phase2.models import (
    EducationalKnowledgeRepresentation,
    Evidence,
    EvidenceLevelEnum,
)
from phase3.errors import RetrievalError

_TOKEN_RE = re.compile(r"[A-Za-z0-9_]+")

# Extremely common English function words carry no retrieval signal but inflate
# document frequencies, which would flatten BM25 scores.
_STOP_TOKENS = frozenset(
    """
    a an the and or but if then than that this these those of in on at to for from by with
    is are was were be been being as it its it's their there here they them we our you your
    he she his her i me my not no nor so such can could may might must shall should will
    would do does did done have has had having what which who whom whose when where why how
    also very much many more most some any each other another into over under about after
    before between during through against above below up down out off again further once
    because while both few nor only own same too s t just don now
    """.split()
)

# Ordinal/section noise: "Chapter 3", "Section 2.1", "Exercise 1.1"
_SECTION_NOISE_RE = re.compile(
    r"^(chapter|section|part|unit|lesson|module|appendix|figure|fig\.?|table|exercise|ex\.|"
    r"problem|question|q\.?)\s*[\d.]*[ivx]*\s*$",
    re.IGNORECASE,
)


def _singularize(token: str) -> str:
    """
    Very light plural folding so morphological variants match.

    Documents and the concepts extracted from them routinely disagree on number
    ("Derivatives" as a heading vs "the derivative of a function" in the prose).
    Without this, BM25 scores both sides zero for such a concept and retrieval
    reports that the material does not cover it.

    Deliberately conservative: only regular plurals are folded, and words of four
    characters or fewer are left alone so genuine stems ("bias", "gas") survive.
    """
    if len(token) <= 4:
        return token
    for suffix in ("ses", "xes", "zes", "ches", "shes"):
        if token.endswith(suffix):
            return token[: -2]
    if token.endswith("ies") and len(token) > 5:
        return token[:-3] + "y"
    if token.endswith("s") and not token.endswith("ss"):
        return token[:-1]
    return token


def tokenize(text: str) -> List[str]:
    """Case-folded, accent-stripped, stopword-filtered, plural-folded token list."""
    if not text:
        return []
    normalized = unicodedata.normalize("NFKD", text)
    ascii_text = "".join(ch for ch in normalized if not unicodedata.combining(ch))
    tokens: List[str] = []
    for raw in (tok.lower() for tok in _TOKEN_RE.findall(ascii_text)):
        if not raw or raw in _STOP_TOKENS:
            continue
        tokens.append(_singularize(raw))
    return tokens


class SourceChunk(BaseModel):
    """A retrievable, citable span of the learner's own material."""

    chunk_id: str
    document_id: str
    page_index: int
    block_id: str
    section_title: Optional[str] = None
    text: str
    score: float = 0.0
    evidence_ids: List[str] = Field(default_factory=list)
    evidence_levels: List[str] = Field(default_factory=list)
    roles: List[str] = Field(default_factory=list)
    block_types: List[str] = Field(default_factory=list)
    concept_ids: List[str] = Field(default_factory=list)

    def citation(self) -> Dict[str, Any]:
        """Citation payload. Every field is derived from the real document structure."""
        return {
            "document_id": self.document_id,
            "page": self.page_index + 1,
            "block_id": self.block_id,
            "section": self.section_title,
            "evidence_ids": self.evidence_ids,
            "quote": _shorten(self.text),
        }


def _shorten(text: str, limit: int = 320) -> str:
    text = " ".join((text or "").split())
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"


class BM25Index:
    """Small in-process BM25 index over the document's semantic blocks."""

    def __init__(self, k1: float = 1.5, b: float = 0.75) -> None:
        self.k1 = k1
        self.b = b
        self.chunks: List[SourceChunk] = []
        self._tokenized: List[List[str]] = []
        self._term_freqs: List[Counter] = []
        self._doc_freq: Counter = Counter()
        self._avg_len: float = 0.0

    def add(self, chunk: SourceChunk) -> None:
        tokens = tokenize(chunk.text)
        self.chunks.append(chunk)
        self._tokenized.append(tokens)
        self._term_freqs.append(Counter(tokens))
        for term in set(tokens):
            self._doc_freq[term] += 1

    def finalize(self) -> None:
        lengths = [len(t) for t in self._tokenized] or [0]
        self._avg_len = sum(lengths) / len(lengths) if lengths else 0.0

    def search(self, query: str, top_k: int = 8) -> List[SourceChunk]:
        q_tokens = tokenize(query)
        if not q_tokens or not self.chunks:
            return []
        n_docs = len(self.chunks)
        results: List[tuple] = []

        for idx, freq in enumerate(self._term_freqs):
            doc_len = len(self._tokenized[idx]) or 1
            score = 0.0
            matched = 0
            for term in set(q_tokens):
                tf = freq.get(term, 0)
                if tf == 0:
                    continue
                matched += 1
                df = self._doc_freq.get(term, 0)
                idf = math.log(1 + (n_docs - df + 0.5) / (df + 0.5))
                denom = tf + self.k1 * (1 - self.b + self.b * doc_len / (self._avg_len or 1))
                score += idf * (tf * (self.k1 + 1)) / denom
            # Require at least half the query terms so unrelated sections do not surface.
            if matched == 0 or matched < max(1, len(set(q_tokens)) // 2):
                continue
            # Normalise by query breadth so long queries do not trivially win.
            results.append((score / max(1, len(set(q_tokens))), idx))

        results.sort(reverse=True)
        out: List[SourceChunk] = []
        for normalised, idx in results[:top_k]:
            chunk = self.chunks[idx].model_copy(deep=True)
            chunk.score = round(normalised, 5)
            out.append(chunk)
        return out


from phase3.retrieval.hybrid_retriever import HybridRetriever, SemanticChunk


class EvidenceRetriever:
    """
    Builds and queries the hybrid retrieval index for a single ingested document.

    Combines BM25 lexical ranking over semantic chunks and atomic blocks, sublinear
    vector cosine similarity, Phase 2 EKR graph traversal, and Reciprocal Rank Fusion.
    """

    def __init__(
        self,
        structured_document,
        ekr: EducationalKnowledgeRepresentation,
    ) -> None:
        self.structured_document = structured_document
        self.ekr = ekr
        self.document_id = getattr(ekr, "source_document_id", None) or structured_document.document_id
        self.index = BM25Index()
        self._chunks_by_block: Dict[str, SourceChunk] = {}
        self._build()
        self._hybrid_retriever = HybridRetriever(structured_document, ekr)

    # -- construction -------------------------------------------------------

    def _section_titles(self) -> Dict[str, str]:
        titles: Dict[str, str] = {}

        def walk(nodes: Sequence[Any]) -> None:
            for node in nodes or []:
                titles[node.section_id] = node.title
                walk(getattr(node, "children", []) or [])

        walk(getattr(self.structured_document, "outline", []) or [])
        return titles

    def _build(self) -> None:
        section_titles = self._section_titles()

        evidence_by_block: Dict[str, List[Evidence]] = {}
        for ev in getattr(self.ekr, "evidence", []) or []:
            evidence_by_block.setdefault(ev.block_id, []).append(ev)

        concepts_by_block: Dict[str, List[str]] = {}
        for mention in getattr(self.ekr, "mentions", []) or []:
            if mention.concept_id:
                concepts_by_block.setdefault(mention.block_id, []).append(mention.concept_id)

        for page in getattr(self.structured_document, "pages", []) or []:
            for block in getattr(page, "blocks", []) or []:
                text = (block.content.text or "").strip()
                if len(text) < 20:
                    continue
                block_type = block.type.value if hasattr(block.type, "value") else str(block.type)
                if block_type in ("page_number", "header", "footer", "watermark"):
                    continue

                evidences = evidence_by_block.get(block.block_id, [])
                chunk = SourceChunk(
                    chunk_id=f"chk_{block.block_id}",
                    document_id=self.document_id,
                    page_index=page.page_index,
                    block_id=block.block_id,
                    section_title=section_titles.get(block.section_id or ""),
                    text=text,
                    evidence_ids=[e.evidence_id for e in evidences],
                    evidence_levels=[e.level.value for e in evidences],
                    roles=[block.role],
                    block_types=[block_type],
                    concept_ids=sorted(set(concepts_by_block.get(block.block_id, []))),
                )
                self.index.add(chunk)
                self._chunks_by_block[block.block_id] = chunk

        self.index.finalize()

    # -- queries ------------------------------------------------------------

    def _concept_terms(self, concept_id: str) -> List[str]:
        """
        Search terms for a concept: its canonical name plus its aliases.
        """
        terms: List[str] = []
        for concept in getattr(self.ekr, "concepts", []) or []:
            if getattr(concept, "concept_id", None) != concept_id:
                continue
            terms.append(getattr(concept, "canonical_name", "") or "")
            for alias in getattr(concept, "aliases", None) or []:
                if isinstance(alias, str):
                    terms.append(alias)
                else:
                    terms.append(getattr(alias, "text", "") or "")
            break
        return [t.strip() for t in terms if t and t.strip()]

    def _to_source_chunk(self, sem: SemanticChunk) -> SourceChunk:
        return SourceChunk(
            chunk_id=sem.chunk_id,
            document_id=sem.document_id,
            page_index=sem.primary_page,
            block_id=sem.primary_block_id,
            section_title=sem.section_title,
            text=sem.text,
            score=sem.score,
            evidence_ids=sem.evidence_ids,
            evidence_levels=sem.evidence_levels,
            roles=sem.roles,
            block_types=sem.block_types,
            concept_ids=sem.concept_ids,
        )

    def retrieve_for_concept(
        self,
        concept_id: str,
        concept_name: Optional[str] = None,
        extra_terms: Optional[Iterable[str]] = None,
        top_k: int = 8,
    ) -> List[SourceChunk]:
        """Rank the document's own passages by relevance to a concept."""
        terms = list(self._concept_terms(concept_id))
        if concept_name:
            terms.insert(0, concept_name)
        terms.extend(extra_terms or [])

        if not terms:
            raise RetrievalError(
                "Cannot ground generation: the concept is not present in the extracted "
                "knowledge representation.",
                details={"concept_id": concept_id},
            )

        query_str = " ".join(terms)
        hybrid_hits = self._hybrid_retriever.search_hybrid(query_str, top_k=top_k)

        if hybrid_hits:
            return [self._to_source_chunk(hit) for hit in hybrid_hits]

        hits = self.index.search(query_str, top_k=top_k)
        if not hits and concept_name:
            hits = self.index.search(concept_name, top_k=top_k)

        if not hits:
            raise RetrievalError(
                "No source passages in the uploaded material relate to this concept, so "
                "LearnSense cannot generate grounded content for it.",
                details={"concept_id": concept_id, "terms": terms[:6]},
            )
        return hits

    def retrieve_by_text(self, query: str, top_k: int = 6) -> List[SourceChunk]:
        hybrid_hits = self._hybrid_retriever.search_hybrid(query, top_k=top_k)
        if hybrid_hits:
            return [self._to_source_chunk(hit) for hit in hybrid_hits]

        hits = self.index.search(query, top_k=top_k)
        if not hits:
            raise RetrievalError(
                "No relevant passages were found in the uploaded material.",
                details={"query": query[:200]},
            )
        return hits

    # -- formatting ---------------------------------------------------------

    @staticmethod
    def format_evidence_for_prompt(chunks: Sequence[SourceChunk], max_chars: int = 9000) -> str:
        """
        Render chunks as an explicitly-labelled evidence block for the LLM prompt.

        Labels carry the real page number and section title so the model can cite them
        accurately and the validator can verify the citation afterwards.
        """
        parts: List[str] = []
        used = 0
        for idx, chunk in enumerate(chunks, start=1):
            section = f", section \"{chunk.section_title}\"" if chunk.section_title else ""
            header = f"[E{idx}] page {chunk.page_index + 1}{section}"
            piece = f"{header}\n{chunk.text.strip()}\n"
            if used + len(piece) > max_chars:
                if used == 0:
                    parts.append(piece[:max_chars])
                break
            parts.append(piece)
            used += len(piece)
        return "\n".join(parts)

    @staticmethod
    def citations(chunks: Sequence[SourceChunk]) -> List[Dict[str, Any]]:
        seen: set = set()
        out: List[Dict[str, Any]] = []
        for chunk in chunks:
            if chunk.block_id in seen:
                continue
            seen.add(chunk.block_id)
            out.append(chunk.citation())
        return out


def evidence_coverage(chunk: SourceChunk) -> float:
    """Fraction of a chunk's sentences explicitly backed by EKR evidence records."""
    if not chunk.evidence_ids:
        return 0.0
    sentences = [s for s in re.split(r"(?<=[.!?])\s+", chunk.text.strip()) if s.strip()]
    if not sentences:
        return 1.0 if chunk.evidence_ids else 0.0
    return min(1.0, len(chunk.evidence_ids) / max(1, len(sentences)))

"""
Hybrid Graph-Augmented Evidence Retrieval Engine for LearnSense Phase 3.

Combines:
1. Lexical BM25 Ranking over atomic blocks and semantic chunks.
2. Dense / Sublinear Vector Cosine Similarity for semantic matching.
3. Phase 2 EKR Knowledge Graph Traversal (Prerequisites, Relationships, Formulas).
4. Reciprocal Rank Fusion (RRF) Reranker.
"""

from __future__ import annotations

import math
import re
import unicodedata
from collections import Counter
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set, Tuple

from phase2.models import EducationalKnowledgeRepresentation
from phase3.errors import RetrievalError
from phase3.retrieval.semantic_chunker import SemanticChunk, SemanticChunker

_TOKEN_RE = re.compile(r"[A-Za-z0-9_]+")

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


def _singularize(token: str) -> str:
    if len(token) <= 4:
        return token
    for suffix in ("ses", "xes", "zes", "ches", "shes"):
        if token.endswith(suffix):
            return token[:-2]
    if token.endswith("ies") and len(token) > 5:
        return token[:-3] + "y"
    if token.endswith("s") and not token.endswith("ss"):
        return token[:-1]
    return token


def tokenize(text: str) -> List[str]:
    """Normalize and tokenize text into informative search tokens."""
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


class VectorSimilarityIndex:
    """
    Fast sublinear TF-IDF vector similarity engine for semantic dense matching.
    """

    def __init__(self) -> None:
        self.chunks: List[SemanticChunk] = []
        self._doc_vectors: List[Dict[str, float]] = []
        self._doc_norms: List[float] = []
        self._doc_freq: Counter = Counter()

    def add(self, chunk: SemanticChunk) -> None:
        tokens = tokenize(chunk.text)
        self.chunks.append(chunk)
        tf = Counter(tokens)
        for term in set(tokens):
            self._doc_freq[term] += 1

    def finalize(self) -> None:
        n_docs = len(self.chunks) or 1
        self._doc_vectors = []
        self._doc_norms = []

        for chunk in self.chunks:
            tokens = tokenize(chunk.text)
            tf = Counter(tokens)
            vec: Dict[str, float] = {}
            norm_sq = 0.0

            for term, count in tf.items():
                df = self._doc_freq.get(term, 1)
                idf = math.log(1.0 + (n_docs / df))
                weight = (1.0 + math.log(count)) * idf
                vec[term] = weight
                norm_sq += weight * weight

            norm = math.sqrt(norm_sq) if norm_sq > 0 else 1.0
            self._doc_vectors.append(vec)
            self._doc_norms.append(norm)

    def search(self, query: str, top_k: int = 10) -> List[Tuple[int, float]]:
        q_tokens = tokenize(query)
        if not q_tokens or not self.chunks:
            return []

        q_tf = Counter(q_tokens)
        n_docs = len(self.chunks) or 1
        q_vec: Dict[str, float] = {}
        q_norm_sq = 0.0

        for term, count in q_tf.items():
            df = self._doc_freq.get(term, 1)
            idf = math.log(1.0 + (n_docs / df))
            weight = (1.0 + math.log(count)) * idf
            q_vec[term] = weight
            q_norm_sq += weight * weight

        q_norm = math.sqrt(q_norm_sq) if q_norm_sq > 0 else 1.0

        scores: List[Tuple[float, int]] = []
        for idx, doc_vec in enumerate(self._doc_vectors):
            dot_product = 0.0
            for term, q_w in q_vec.items():
                if term in doc_vec:
                    dot_product += q_w * doc_vec[term]

            if dot_product > 0:
                cosine_sim = dot_product / (q_norm * self._doc_norms[idx])
                scores.append((cosine_sim, idx))

        scores.sort(reverse=True)
        return [(idx, score) for score, idx in scores[:top_k]]


class KnowledgeGraphRetriever:
    """
    Traverses Phase 2 EKR graph relationships to discover graph-neighbor evidence.
    """

    def __init__(self, ekr: Optional[EducationalKnowledgeRepresentation]) -> None:
        self.ekr = ekr
        self._concept_by_id: Dict[str, Any] = {}
        self._concept_by_name: Dict[str, str] = {}
        self._graph_adj: Dict[str, List[Tuple[str, str]]] = {}  # concept_id -> [(neighbor_id, rel_type)]
        self._block_to_concepts: Dict[str, Set[str]] = {}
        self._concept_to_blocks: Dict[str, Set[str]] = {}
        self._build_graph()

    def _build_graph(self) -> None:
        if self.ekr is None:
            return

        for concept in getattr(self.ekr, "concepts", []) or []:
            c_id = getattr(concept, "concept_id", None)
            if not c_id:
                continue
            self._concept_by_id[c_id] = concept
            c_name = getattr(concept, "canonical_name", "").lower()
            if c_name:
                self._concept_by_name[c_name] = c_id
            for alias in getattr(concept, "aliases", []) or []:
                a_text = alias if isinstance(alias, str) else getattr(alias, "text", "")
                if a_text:
                    self._concept_by_name[a_text.lower()] = c_id

        # Index relationships
        for rel in getattr(self.ekr, "relationships", []) or []:
            s_id = getattr(rel, "source", getattr(rel, "source_id", None))
            t_id = getattr(rel, "target", getattr(rel, "target_id", None))
            rel_type = getattr(rel, "type", getattr(rel, "relationship_type", ""))
            rel_type_str = getattr(rel_type, "value", str(rel_type))
            if s_id and t_id:
                self._graph_adj.setdefault(s_id, []).append((t_id, rel_type_str))
                self._graph_adj.setdefault(t_id, []).append((s_id, f"inv_{rel_type_str}"))

        # Index mentions / block linkages
        for mention in getattr(self.ekr, "mentions", []) or []:
            b_id = getattr(mention, "block_id", None)
            c_id = getattr(mention, "concept_id", None)
            if b_id and c_id:
                self._block_to_concepts.setdefault(b_id, set()).add(c_id)
                self._concept_to_blocks.setdefault(c_id, set()).add(b_id)

        # Index evidence block linkages
        for ev in getattr(self.ekr, "evidence", []) or []:
            b_id = getattr(ev, "block_id", None)
            if b_id:
                for c_id, concept in self._concept_by_id.items():
                    if getattr(ev, "evidence_id", "") in getattr(concept, "evidence_ids", []):
                        self._block_to_concepts.setdefault(b_id, set()).add(c_id)
                        self._concept_to_blocks.setdefault(c_id, set()).add(b_id)

    def traverse_neighbors(self, query_terms: Sequence[str], max_hops: int = 2) -> Dict[str, float]:
        """
        Returns a mapping of block_id -> graph_relevance_score based on 1-hop and 2-hop neighbors.
        """
        if not self._concept_by_id:
            return {}

        seed_concepts: Set[str] = set()
        for term in query_terms:
            t_low = term.lower()
            if t_low in self._concept_by_name:
                seed_concepts.add(self._concept_by_name[t_low])
            for name, c_id in self._concept_by_name.items():
                if t_low in name or name in t_low:
                    seed_concepts.add(c_id)

        block_scores: Dict[str, float] = {}

        # Direct concept blocks (score = 1.0)
        for c_id in seed_concepts:
            for b_id in self._concept_to_blocks.get(c_id, set()):
                block_scores[b_id] = max(block_scores.get(b_id, 0.0), 1.0)

            # 1-hop graph neighbors (score = 0.6)
            for neighbor_id, _ in self._graph_adj.get(c_id, []):
                for b_id in self._concept_to_blocks.get(neighbor_id, set()):
                    block_scores[b_id] = max(block_scores.get(b_id, 0.0), 0.6)

                # 2-hop graph neighbors (score = 0.3)
                if max_hops >= 2:
                    for n2_id, _ in self._graph_adj.get(neighbor_id, []):
                        if n2_id != c_id:
                            for b_id in self._concept_to_blocks.get(n2_id, set()):
                                block_scores[b_id] = max(block_scores.get(b_id, 0.0), 0.3)

        return block_scores


class HybridRetriever:
    """
    Unified Hybrid Retrieval Engine (BM25 + Dense TF-IDF Vectors + EKR Graph Traversal + RRF).
    """

    def __init__(
        self,
        structured_document: Any,
        ekr: Optional[EducationalKnowledgeRepresentation] = None,
        rrf_k: int = 60,
    ) -> None:
        self.structured_document = structured_document
        self.ekr = ekr
        self.rrf_k = rrf_k
        self.document_id = getattr(structured_document, "document_id", "doc_unknown")

        chunker = SemanticChunker()
        self.chunks = chunker.chunk_document(structured_document, ekr)
        self.vector_index = VectorSimilarityIndex()
        self.graph_retriever = KnowledgeGraphRetriever(ekr)

        self._bm25_tokenized: List[List[str]] = []
        self._bm25_term_freqs: List[Counter] = []
        self._bm25_doc_freq: Counter = Counter()
        self._bm25_avg_len: float = 0.0

        self._build_indices()

    def _build_indices(self) -> None:
        for chunk in self.chunks:
            tokens = tokenize(chunk.text)
            self._bm25_tokenized.append(tokens)
            self._bm25_term_freqs.append(Counter(tokens))
            for term in set(tokens):
                self._bm25_doc_freq[term] += 1
            self.vector_index.add(chunk)

        lengths = [len(t) for t in self._bm25_tokenized] or [0]
        self._bm25_avg_len = sum(lengths) / len(lengths) if lengths else 0.0
        self.vector_index.finalize()

    def _bm25_search(self, query: str, top_k: int = 15) -> List[Tuple[int, float]]:
        q_tokens = tokenize(query)
        if not q_tokens or not self.chunks:
            return []

        n_docs = len(self.chunks)
        results: List[Tuple[float, int]] = []
        k1, b = 1.5, 0.75

        for idx, freq in enumerate(self._bm25_term_freqs):
            doc_len = len(self._bm25_tokenized[idx]) or 1
            score = 0.0
            matched = 0

            for term in set(q_tokens):
                tf = freq.get(term, 0)
                if tf == 0:
                    continue
                matched += 1
                df = self._bm25_doc_freq.get(term, 0)
                idf = math.log(1 + (n_docs - df + 0.5) / (df + 0.5))
                denom = tf + k1 * (1 - b + b * doc_len / (self._bm25_avg_len or 1))
                score += idf * (tf * (k1 + 1)) / denom

            if matched > 0:
                normalised = score / max(1, len(set(q_tokens)))
                results.append((normalised, idx))

        results.sort(reverse=True)
        return [(idx, score) for score, idx in results[:top_k]]

    def search_hybrid(
        self,
        query: str,
        top_k: int = 8,
        lexical_weight: float = 1.0,
        vector_weight: float = 0.8,
        graph_weight: float = 0.7,
    ) -> List[SemanticChunk]:
        """
        Executes multi-channel retrieval and fuses via Reciprocal Rank Fusion (RRF).
        """
        if not query or not self.chunks:
            return []

        # 1. Lexical BM25 Channel
        bm25_hits = self._bm25_search(query, top_k=20)
        bm25_ranks: Dict[int, int] = {idx: rank for rank, (idx, _) in enumerate(bm25_hits, start=1)}

        # 2. Vector Semantic Channel
        vector_hits = self.vector_index.search(query, top_k=20)
        vector_ranks: Dict[int, int] = {idx: rank for rank, (idx, _) in enumerate(vector_hits, start=1)}

        # 3. Knowledge Graph Channel
        q_tokens = tokenize(query)
        graph_block_scores = self.graph_retriever.traverse_neighbors(q_tokens)
        graph_chunk_hits: List[Tuple[float, int]] = []

        for idx, chunk in enumerate(self.chunks):
            chunk_graph_score = max((graph_block_scores.get(b_id, 0.0) for b_id in chunk.block_ids), default=0.0)
            if chunk_graph_score > 0:
                graph_chunk_hits.append((chunk_graph_score, idx))

        graph_chunk_hits.sort(reverse=True)
        graph_ranks: Dict[int, int] = {idx: rank for rank, (_, idx) in enumerate(graph_chunk_hits, start=1)}

        # 4. Reciprocal Rank Fusion
        candidate_indices = set(bm25_ranks.keys()) | set(vector_ranks.keys()) | set(graph_ranks.keys())
        if not candidate_indices:
            return []

        rrf_scores: List[Tuple[float, int]] = []
        for idx in candidate_indices:
            score = 0.0
            if idx in bm25_ranks:
                score += lexical_weight / (self.rrf_k + bm25_ranks[idx])
            if idx in vector_ranks:
                score += vector_weight / (self.rrf_k + vector_ranks[idx])
            if idx in graph_ranks:
                score += graph_weight / (self.rrf_k + graph_ranks[idx])
            rrf_scores.append((score, idx))

        rrf_scores.sort(reverse=True)

        results: List[SemanticChunk] = []
        for score, idx in rrf_scores[:top_k]:
            chunk_copy = self.chunks[idx].model_copy(deep=True)
            chunk_copy.score = round(score, 5)
            results.append(chunk_copy)

        return results

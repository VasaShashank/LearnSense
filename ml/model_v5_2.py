"""LearnSense Person 3 — v5.2 Corrected Architecture & Causal Engine.

Corrects:
1. Response-History Temporal Alignment:
   - Query at step t cannot see response y_t.
   - Query at step t attends to start_context and all past interactions context[0...t-1],
     each of which incorporates its historical response y_0...y_{t-1}.
   - Future responses remain strictly masked.
2. Multi-Concept Mastery Supervision:
   - Evaluates and supervises all assessed concepts (primary and secondary) simultaneously.
   - Uses binary concept masks to prevent false zero-mastery penalties.
3. Arbitrary Concept Mastery Interface:
   - PredictMasteryService supports querying any concept at any trajectory step without questions.
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F

MAX_RELATIVE_DISTANCE = 64


class AKTMasteryHeadV52(nn.Module):
    """Corrected AKT + Multi-Concept Mastery Head (v5.2)."""

    def __init__(
        self,
        n_questions: int = 1751,
        n_concepts: int = 88,
        n_difficulties: int = 4,
        d_model: int = 64,
        n_heads: int = 4,
        dropout: float = 0.1,
    ) -> None:
        super().__init__()
        self.d_model = d_model
        self.n_heads = n_heads
        self.n_concepts = n_concepts
        self.head_dim = d_model // n_heads
        if self.head_dim * n_heads != d_model:
            raise ValueError(f"d_model ({d_model}) must be divisible by n_heads ({n_heads}).")

        # Embeddings
        self.question_embedding = nn.Embedding(n_questions, d_model)
        self.concept_embedding = nn.Embedding(n_concepts, d_model)
        self.difficulty_embedding = nn.Embedding(n_difficulties, d_model)
        self.response_embedding = nn.Embedding(2, d_model) # 0: incorrect, 1: correct

        # Causal Context GRU
        self.context_encoder = nn.GRU(d_model, d_model, batch_first=True)
        self.start_context = nn.Parameter(torch.zeros(d_model))

        # Causal Attention Projections
        self.query_projection = nn.Linear(d_model, d_model)
        self.key_projection = nn.Linear(d_model, d_model)
        self.value_projection = nn.Linear(d_model, d_model)
        self.output_projection = nn.Linear(d_model, d_model)

        # Relative position bias
        self.relative_bias = nn.Parameter(torch.zeros(MAX_RELATIVE_DISTANCE, n_heads))
        self.norm1 = nn.LayerNorm(d_model)
        self.norm2 = nn.LayerNorm(d_model)

        self.feed_forward = nn.Sequential(
            nn.Linear(d_model, d_model * 4),
            nn.GELU(),
            nn.Dropout(dropout),
            nn.Linear(d_model * 4, d_model),
            nn.Dropout(dropout),
        )

        # Rasch item bias
        self.item_bias = nn.Embedding(n_questions, 1)

        # Head 1: Response prediction head
        self.response_head = nn.Sequential(
            nn.Linear(d_model * 2, d_model),
            nn.GELU(),
            nn.Dropout(dropout),
            nn.Linear(d_model, 1),
        )

        # Head 2: Concept mastery estimation head (projects to all concepts)
        self.mastery_proj = nn.Sequential(
            nn.Linear(d_model, d_model),
            nn.GELU(),
            nn.Dropout(dropout),
        )
        self.mastery_head = nn.Linear(d_model, n_concepts)

    def forward(
        self,
        questions: torch.Tensor,     # [batch, length]
        concepts: torch.Tensor,      # [batch, length]
        difficulties: torch.Tensor,  # [batch, length]
        responses: torch.Tensor,     # [batch, length] (response y_t at step t)
        mask: torch.Tensor,          # [batch, length]
    ) -> Tuple[torch.Tensor, torch.Tensor]:
        """Forward pass with mathematically verified causal alignment.
        
        Guarantees:
        - Query at step t is item t (q_t, c_t, d_t) WITHOUT response y_t.
        - Attended keys for query t are start_context (pos 0) and context[0...t-1] (pos 1...t).
        - context[t] (which incorporates response y_t) is STRICTLY MASKED OUT at step t.
        - Future steps > t are STRICTLY MASKED OUT.
        """
        batch, length = questions.shape
        device = questions.device

        # 1. Query Item Vector at step t (available before response)
        query = (
            self.question_embedding(questions)
            + self.concept_embedding(concepts)
            + self.difficulty_embedding(difficulties)
        )

        # 2. Context Representation
        # context_input at step j combines query j with observed response y_j
        clamped_responses = responses.clamp(0, 1)
        context_input = query + self.response_embedding(clamped_responses)
        context, _ = self.context_encoder(context_input) # [batch, length, d_model]

        # 3. Key/Value Tensor
        # Pos 0: start_context (prior state before any interactions)
        # Pos 1...length: context[0...length-1] (contains interaction j including response y_j)
        key_value = torch.cat(
            [self.start_context.view(1, 1, -1).expand(batch, -1, -1), context],
            dim=1,
        ) # [batch, length + 1, d_model]

        q = self.query_projection(query).view(batch, length, self.n_heads, self.head_dim).transpose(1, 2)
        k = self.key_projection(key_value).view(batch, length + 1, self.n_heads, self.head_dim).transpose(1, 2)
        v = self.value_projection(key_value).view(batch, length + 1, self.n_heads, self.head_dim).transpose(1, 2)

        scores = torch.matmul(q, k.transpose(-2, -1)) / math.sqrt(self.head_dim) # [batch, n_heads, length, length + 1]

        # Relative position bias for historical steps (cols 1...length)
        positions = torch.arange(length, device=device)
        history_positions = torch.arange(length, device=device)
        distance = (positions.view(-1, 1) - history_positions.view(1, -1)).clamp(0, MAX_RELATIVE_DISTANCE - 1)
        history_bias = self.relative_bias[distance].permute(2, 0, 1) # [n_heads, length, length]
        
        # Add relative bias to history positions (cols 1...length+1) without modifying in-place
        scores_history = scores[..., 1:] + history_bias.unsqueeze(0)
        scores = torch.cat([scores[..., :1], scores_history], dim=-1)

        # 4. Strict Causal Masking
        # Query at row t (0 <= t < length) can attend to:
        # - Column 0: start_context (always allowed)
        # - Column j+1: context[j] for j < t (historical interactions 0 <= j <= t-1)
        # - Column t+1: context[t] (contains response y_t) is FORBIDDEN!
        # - Column j+1 for j > t: future interactions are FORBIDDEN!
        allowed_history = history_positions.view(1, -1) < positions.view(-1, 1) # [length, length]
        start_allowed = torch.ones((batch, length, 1), dtype=torch.bool, device=device)
        allowed_total = torch.cat([start_allowed, allowed_history.unsqueeze(0).expand(batch, -1, -1)], dim=2) # [batch, length, length + 1]
        attention_mask = ~allowed_total # True where masked

        # Key padding mask: start_context is never padded; context[j] padded if ~mask[j]
        key_padding_mask = ~torch.cat(
            [torch.ones((batch, 1), dtype=torch.bool, device=device), mask],
            dim=1,
        ) # [batch, length + 1]

        scores = scores.masked_fill(attention_mask.unsqueeze(1), -1e9)
        scores = scores.masked_fill(key_padding_mask[:, None, None, :], -1e9)
        attention = torch.softmax(scores, dim=-1)
        attended = torch.matmul(attention, v).transpose(1, 2).reshape(batch, length, self.d_model)

        # Residual + Norm + FeedForward
        attended = self.norm1(query + self.output_projection(attended))
        contextual = self.norm2(attended + self.feed_forward(attended))

        # Head 1: Response logits
        combined_repr = torch.cat([contextual, query], dim=-1)
        response_logits = self.response_head(combined_repr).squeeze(-1) + self.item_bias(questions).squeeze(-1)

        # Head 2: Concept mastery logits for ALL concepts
        mastery_repr = self.mastery_proj(contextual)
        all_mastery_logits = self.mastery_head(mastery_repr) # [batch, length, n_concepts]

        return response_logits, all_mastery_logits


class PredictMasteryService:
    """Production service for querying concept mastery and next-question correctness
    using the exact trained computation graph of AKTMasteryHeadV52.

    Adheres strictly to the 2026.jee.v1 canonical curriculum contract:
    - 87 active canonical concepts (indices 1...87).
    - Index 0 is strictly reserved as <pad>/<unknown>.
    - Fail-fast validation: invalid concept IDs raise KeyError.
    - Full causal consistency: state at step T incorporates exactly interactions 0...T-1.
    - Zero future leakage: current/unanswered interactions cannot affect current predictions.
    - Multi-concept projection head: uses full transformer attention, residual, norm, and FFN.
    """

    def __init__(
        self,
        model: AKTMasteryHeadV52,
        vocab_path: str | Path = "experiments/v5_2_retraining/v5_2_vocabulary.json",
    ) -> None:
        self.model = model
        self.model.eval()
        self.device = next(model.parameters()).device

        # Load authoritative vocabulary mapping
        vocab_path = Path(vocab_path)
        if vocab_path.exists():
            with open(vocab_path, "r", encoding="utf-8") as f:
                vocab = json.load(f)
            self.concept_to_idx: Dict[str, int] = vocab.get("concept_to_idx", {})
            self.idx_to_concept: Dict[int, str] = {int(k): v for k, v in vocab.get("idx_to_concept", {}).items()}
            self.question_to_idx: Dict[str, int] = vocab.get("question_to_idx", {})
        else:
            self.concept_to_idx = {}
            self.idx_to_concept = {}
            self.question_to_idx = {}

        self.diff_to_idx: Dict[str, int] = {"easy": 0, "medium": 1, "hard": 2, "unknown": 3}

    def resolve_concept_idx(self, concept: str | int) -> int:
        """Resolves external canonical string or integer concept ID to internal index in [1, 87].
        Raises KeyError if invalid, unknown, or reserved index 0. Never returns default.
        """
        if isinstance(concept, int):
            if 1 <= concept <= 87:
                return concept
            if concept == 0:
                raise KeyError(
                    "Concept index 0 is strictly reserved as <pad>/<unknown> and is not a valid curriculum concept."
                )
            raise KeyError(
                f"Invalid concept index '{concept}'. Valid canonical concepts are indices 1..87."
            )
        concept_str = str(concept).strip()
        if concept_str in self.concept_to_idx:
            idx = self.concept_to_idx[concept_str]
            if 1 <= idx <= 87:
                return idx
        raise KeyError(
            f"Concept '{concept_str}' is not an active canonical concept in curriculum 2026.jee.v1."
        )

    def resolve_question_idx(self, question: str | int) -> int:
        """Resolves external question ID to internal index in [1, 1750]. Returns 0 if unknown/unspecified."""
        if isinstance(question, int):
            if 1 <= question <= 1750:
                return question
            return 0
        return self.question_to_idx.get(str(question).strip(), 0)

    def resolve_difficulty_idx(self, diff: str | int) -> int:
        """Resolves difficulty string to integer index in [0, 3]."""
        if isinstance(diff, int):
            return min(max(diff, 0), 3)
        return self.diff_to_idx.get(str(diff).lower().strip(), 3)

    def _compute_key_value_context(
        self,
        student_history: Optional[List[Dict[str, Any]]],
    ) -> Tuple[torch.Tensor, int]:
        """Computes key-value representations from observed interaction history 0...T-1.
        
        Guarantees:
        - T = 0 (cold start): returns start_context at pos 0.
        - T >= 1: returns [start_context, context_0, ..., context_{T-1}].
        - Exactly observed interactions are incorporated. Zero future interaction leakage.
        """
        if not student_history:
            kv = self.model.start_context.view(1, 1, -1) # [1, 1, d_model]
            return kv, 0

        T = len(student_history)
        q_list, c_list, d_list, r_list = [], [], [], []
        for i, item in enumerate(student_history):
            q_idx = self.resolve_question_idx(item.get("question_id", 0))
            c_idx = self.resolve_concept_idx(item["concept_id"])
            d_idx = self.resolve_difficulty_idx(item.get("difficulty", 3))
            r_val = int(item["correct"])
            if r_val not in (0, 1):
                raise ValueError(f"Interaction {i} response 'correct' must be 0 or 1, got {r_val}")
            q_list.append(q_idx)
            c_list.append(c_idx)
            d_list.append(d_idx)
            r_list.append(r_val)

        q_arr = torch.tensor([q_list], dtype=torch.long, device=self.device)
        c_arr = torch.tensor([c_list], dtype=torch.long, device=self.device)
        d_arr = torch.tensor([d_list], dtype=torch.long, device=self.device)
        r_arr = torch.tensor([r_list], dtype=torch.long, device=self.device)

        query_hist = (
            self.model.question_embedding(q_arr)
            + self.model.concept_embedding(c_arr)
            + self.model.difficulty_embedding(d_arr)
        )
        context_input = query_hist + self.model.response_embedding(r_arr.clamp(0, 1))
        context, _ = self.model.context_encoder(context_input) # [1, T, d_model]

        key_value = torch.cat(
            [self.model.start_context.view(1, 1, -1), context],
            dim=1,
        ) # [1, T + 1, d_model]
        return key_value, T

    def _evaluate_query_contextual(
        self,
        key_value: torch.Tensor,
        T: int,
        Q_items: torch.Tensor,
    ) -> torch.Tensor:
        """Applies trained multi-head causal attention, normalization, and FFN layers.
        
        Q_items: [B, 1, d_model] query representation.
        Returns: contextual representation [B, 1, d_model] matching trained pathway.
        """
        B = Q_items.shape[0]
        n_heads = self.model.n_heads
        head_dim = self.model.head_dim

        q = self.model.query_projection(Q_items).view(B, 1, n_heads, head_dim).transpose(1, 2) # [B, n_heads, 1, head_dim]
        kv_exp = key_value.expand(B, -1, -1) # [B, T + 1, d_model]
        k = self.model.key_projection(kv_exp).view(B, T + 1, n_heads, head_dim).transpose(1, 2) # [B, n_heads, T + 1, head_dim]
        v = self.model.value_projection(kv_exp).view(B, T + 1, n_heads, head_dim).transpose(1, 2) # [B, n_heads, T + 1, head_dim]

        scores = torch.matmul(q, k.transpose(-2, -1)) / math.sqrt(head_dim) # [B, n_heads, 1, T + 1]

        if T > 0:
            # Query at position T attending to history positions 0...T-1
            history_positions = torch.arange(T, device=self.device).view(1, -1)
            dist = (torch.tensor([[T]], device=self.device) - history_positions).clamp(0, MAX_RELATIVE_DISTANCE - 1)
            h_bias = self.model.relative_bias[dist].permute(2, 0, 1) # [n_heads, 1, T]
            scores_hist = scores[..., 1:] + h_bias.unsqueeze(0)
            scores = torch.cat([scores[..., :1], scores_hist], dim=-1)

        attention = torch.softmax(scores, dim=-1)
        attended = torch.matmul(attention, v).transpose(1, 2).reshape(B, 1, self.model.d_model)

        # Residual + Norm1 + FFN + Norm2
        attended = self.model.norm1(Q_items + self.model.output_projection(attended))
        contextual = self.model.norm2(attended + self.model.feed_forward(attended))
        return contextual

    def predict_mastery(
        self,
        student_history: Optional[List[Dict[str, Any]]],
        concept_id: str | int,
        question_id: Optional[str | int] = None,
        difficulty: Optional[str | int] = None,
    ) -> float:
        """Returns estimated mastery in [0, 1] for an arbitrary concept_id after history.
        
        If question_id and difficulty are provided, computes mastery using the exact item query
        as in the trained sequence pathway. If omitted, queries concept using canonical embedding.
        """
        c_idx = self.resolve_concept_idx(concept_id)

        with torch.no_grad():
            key_value, T = self._compute_key_value_context(student_history)

            if question_id is not None:
                q_idx = self.resolve_question_idx(question_id)
                d_idx = self.resolve_difficulty_idx(difficulty if difficulty is not None else 3)
                Q_item = (
                    self.model.question_embedding(torch.tensor([[q_idx]], device=self.device))
                    + self.model.concept_embedding(torch.tensor([[c_idx]], device=self.device))
                    + self.model.difficulty_embedding(torch.tensor([[d_idx]], device=self.device))
                )
            else:
                Q_item = self.model.concept_embedding(torch.tensor([[c_idx]], device=self.device))

            contextual = self._evaluate_query_contextual(key_value, T, Q_item)
            mastery_repr = self.model.mastery_proj(contextual)
            logits = self.model.mastery_head(mastery_repr)
            return float(torch.sigmoid(logits[0, 0, c_idx]).cpu().item())

    def get_student_mastery_vector(
        self,
        student_history: Optional[List[Dict[str, Any]]] = None,
    ) -> np.ndarray:
        """Returns 88-dimensional continuous mastery estimates for all concepts in curriculum.
        
        Index 0 is 0.0 (reserved <pad>).
        Indices 1...87 contain personalized mastery probabilities in [0, 1].
        Evaluates all 87 concepts in parallel through the complete trained computation graph.
        """
        with torch.no_grad():
            key_value, T = self._compute_key_value_context(student_history)

            # Query all 87 canonical concepts in parallel: [87, 1, d_model]
            all_concepts = torch.arange(1, 88, device=self.device).view(87, 1)
            Q_items = self.model.concept_embedding(all_concepts)

            contextual = self._evaluate_query_contextual(key_value, T, Q_items)
            mastery_repr = self.model.mastery_proj(contextual)
            logits = self.model.mastery_head(mastery_repr) # [87, 1, 88]

            vec = np.zeros(88, dtype=np.float32)
            # Extract diagonal matching each concept's respective logit
            diag_logits = torch.stack([logits[i, 0, i + 1] for i in range(87)])
            vec[1:] = torch.sigmoid(diag_logits).cpu().numpy()
            return vec

    def predict_next_correctness(
        self,
        student_history: Optional[List[Dict[str, Any]]],
        question_id: str | int,
        concept_id: str | int,
        difficulty: Optional[str | int] = "unknown",
    ) -> float:
        """Predicts probability P(correct=1) for an upcoming question item."""
        q_idx = self.resolve_question_idx(question_id)
        c_idx = self.resolve_concept_idx(concept_id)
        d_idx = self.resolve_difficulty_idx(difficulty)

        with torch.no_grad():
            key_value, T = self._compute_key_value_context(student_history)

            Q_item = (
                self.model.question_embedding(torch.tensor([[q_idx]], device=self.device))
                + self.model.concept_embedding(torch.tensor([[c_idx]], device=self.device))
                + self.model.difficulty_embedding(torch.tensor([[d_idx]], device=self.device))
            )

            contextual = self._evaluate_query_contextual(key_value, T, Q_item)
            combined = torch.cat([contextual, Q_item], dim=-1)
            q_tensor = torch.tensor([[q_idx]], device=self.device)
            resp_logit = self.model.response_head(combined).squeeze(-1) + self.model.item_bias(q_tensor).squeeze(-1)
            return float(torch.sigmoid(resp_logit[0, 0]).cpu().item())


"""Causal neural knowledge-tracing models for the comprehensive benchmark.

SAKT follows the self-attentive knowledge tracing pattern with a strict causal
mask. AKT is an adapted AKT-style model with a causal context encoder,
relative-position-biased attention, and a Rasch-style item term. It is not an
exact reproduction of the published AKT architecture.
"""

from __future__ import annotations

import copy
import math
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np
import pandas as pd
import torch
from torch import nn
from torch.utils.data import DataLoader

from src.baselines import PROBABILITY_EPSILON

START_RESPONSE = 2
MAX_RELATIVE_DISTANCE = 64


def _clip(values: Sequence[float]) -> np.ndarray:
    return np.clip(np.asarray(values, dtype=float), PROBABILITY_EPSILON, 1.0 - PROBABILITY_EPSILON)


@dataclass
class Vocabulary:
    question_to_index: Dict[str, int]
    concept_to_index: Dict[str, int]
    difficulty_to_index: Dict[str, int]

    @classmethod
    def from_train(cls, train_targets: pd.DataFrame) -> "Vocabulary":
        questions = sorted(train_targets["question_id"].astype(str).unique())
        concepts = sorted(train_targets["primary_concept_id"].astype(str).unique())
        difficulties = sorted(train_targets["difficulty"].astype(str).unique())
        return cls(
            question_to_index={value: index + 1 for index, value in enumerate(questions)},
            concept_to_index={value: index + 1 for index, value in enumerate(concepts)},
            difficulty_to_index={value: index + 1 for index, value in enumerate(difficulties)},
        )

    @property
    def n_questions(self) -> int:
        return len(self.question_to_index) + 1

    @property
    def n_concepts(self) -> int:
        return len(self.concept_to_index) + 1

    @property
    def n_difficulties(self) -> int:
        return len(self.difficulty_to_index) + 1

    def to_dict(self) -> Dict[str, Any]:
        return {
            "n_questions": self.n_questions,
            "n_concepts": self.n_concepts,
            "n_difficulties": self.n_difficulties,
            "question_oov_index": 0,
            "concept_oov_index": 0,
            "difficulty_oov_index": 0,
        }


@dataclass
class SequenceArrays:
    interaction_ids: np.ndarray
    questions: np.ndarray
    concepts: np.ndarray
    difficulties: np.ndarray
    previous_responses: np.ndarray
    correct: np.ndarray

    def __len__(self) -> int:
        return len(self.correct)


def build_sequences(targets: pd.DataFrame, vocabulary: Vocabulary) -> List[SequenceArrays]:
    df = targets.sort_values(
        by=["student_id", "sequence_index", "timestamp_utc"],
        kind="mergesort",
    )
    sequences: List[SequenceArrays] = []
    for _, group in df.groupby("student_id", sort=False):
        questions = group["question_id"].astype(str).map(vocabulary.question_to_index).fillna(0).to_numpy(dtype=np.int64)
        concepts = (
            group["primary_concept_id"]
            .astype(str)
            .map(vocabulary.concept_to_index)
            .fillna(0)
            .to_numpy(dtype=np.int64)
        )
        difficulties = (
            group["difficulty"]
            .astype(str)
            .map(vocabulary.difficulty_to_index)
            .fillna(0)
            .to_numpy(dtype=np.int64)
        )
        correct = group["correct"].to_numpy(dtype=np.int64)
        previous = np.empty_like(correct)
        previous[0] = START_RESPONSE
        if len(correct) > 1:
            previous[1:] = correct[:-1]
        sequences.append(
            SequenceArrays(
                interaction_ids=group["interaction_id"].astype(str).to_numpy(),
                questions=questions,
                concepts=concepts,
                difficulties=difficulties,
                previous_responses=previous,
                correct=correct,
            )
        )
    return sequences


def collate_sequences(sequences: Sequence[SequenceArrays]) -> Dict[str, Any]:
    max_len = max(len(sequence) for sequence in sequences)
    batch = len(sequences)
    questions = torch.zeros((batch, max_len), dtype=torch.long)
    concepts = torch.zeros((batch, max_len), dtype=torch.long)
    difficulties = torch.zeros((batch, max_len), dtype=torch.long)
    responses = torch.full((batch, max_len), START_RESPONSE, dtype=torch.long)
    correct = torch.zeros((batch, max_len), dtype=torch.float32)
    mask = torch.zeros((batch, max_len), dtype=torch.bool)
    interaction_ids: List[str] = []
    for row, sequence in enumerate(sequences):
        length = len(sequence)
        questions[row, :length] = torch.from_numpy(sequence.questions)
        concepts[row, :length] = torch.from_numpy(sequence.concepts)
        difficulties[row, :length] = torch.from_numpy(sequence.difficulties)
        responses[row, :length] = torch.from_numpy(sequence.correct.astype(np.int64))
        correct[row, :length] = torch.from_numpy(sequence.correct.astype(np.float32))
        mask[row, :length] = True
        interaction_ids.extend(sequence.interaction_ids.tolist())
        interaction_ids.extend([""] * (max_len - length))
    return {
        "questions": questions,
        "concepts": concepts,
        "difficulties": difficulties,
        "responses": responses,
        "correct": correct,
        "mask": mask,
        "interaction_ids": interaction_ids,
    }


class _AttentionBlock(nn.Module):
    def __init__(self, d_model: int, n_heads: int, dropout: float) -> None:
        super().__init__()
        self.n_heads = n_heads
        self.attention = nn.MultiheadAttention(
            d_model,
            n_heads,
            dropout=dropout,
            batch_first=True,
        )
        self.norm1 = nn.LayerNorm(d_model)
        self.norm2 = nn.LayerNorm(d_model)
        self.feed_forward = nn.Sequential(
            nn.Linear(d_model, d_model * 4),
            nn.GELU(),
            nn.Dropout(dropout),
            nn.Linear(d_model * 4, d_model),
            nn.Dropout(dropout),
        )

    def forward(
        self,
        query: torch.Tensor,
        key_value: torch.Tensor,
        attention_mask: torch.Tensor,
        key_padding_mask: torch.Tensor,
    ) -> torch.Tensor:
        expanded_mask = attention_mask.repeat_interleave(self.n_heads, dim=0)
        attended, _ = self.attention(
            query,
            key_value,
            key_value,
            attn_mask=expanded_mask,
            key_padding_mask=key_padding_mask,
            need_weights=False,
        )
        hidden = self.norm1(query + attended)
        return self.norm2(hidden + self.feed_forward(hidden))


class SAKTModel(nn.Module):
    def __init__(
        self,
        n_questions: int,
        n_concepts: int,
        n_difficulties: int,
        *,
        d_model: int = 64,
        n_heads: int = 4,
        n_layers: int = 2,
        dropout: float = 0.1,
    ) -> None:
        super().__init__()
        self.question_embedding = nn.Embedding(n_questions, d_model)
        self.concept_embedding = nn.Embedding(n_concepts, d_model)
        self.difficulty_embedding = nn.Embedding(n_difficulties, d_model)
        self.response_embedding = nn.Embedding(3, d_model)
        self.start_key_value = nn.Parameter(torch.zeros(d_model))
        self.blocks = nn.ModuleList(
            [_AttentionBlock(d_model, n_heads, dropout) for _ in range(n_layers)]
        )
        self.head = nn.Sequential(
            nn.Linear(d_model * 2, d_model),
            nn.GELU(),
            nn.Dropout(dropout),
            nn.Linear(d_model, 1),
        )

    def forward(
        self,
        questions: torch.Tensor,
        concepts: torch.Tensor,
        difficulties: torch.Tensor,
        responses: torch.Tensor,
        mask: torch.Tensor,
    ) -> torch.Tensor:
        batch, length = questions.shape
        query = (
            self.question_embedding(questions)
            + self.concept_embedding(concepts)
            + self.difficulty_embedding(difficulties)
        )
        history = query + self.response_embedding(responses)
        key_value = torch.cat(
            [self.start_key_value.view(1, 1, -1).expand(batch, -1, -1), history],
            dim=1,
        )
        positions = torch.arange(length, device=questions.device)
        history_positions = torch.arange(length, device=questions.device)
        allowed = history_positions.view(1, -1) < positions.view(-1, 1)
        allowed = allowed.unsqueeze(0).expand(batch, -1, -1)
        start_allowed = torch.ones((batch, length, 1), dtype=torch.bool, device=questions.device)
        attention_mask = ~torch.cat([start_allowed, allowed], dim=2)
        key_padding_mask = ~torch.cat(
            [torch.ones((batch, 1), dtype=torch.bool, device=questions.device), mask],
            dim=1,
        )
        hidden = query
        for block in self.blocks:
            hidden = block(hidden, key_value, attention_mask, key_padding_mask)
        return self.head(torch.cat([hidden, query], dim=-1)).squeeze(-1)


class AKTAdapterModel(nn.Module):
    def __init__(
        self,
        n_questions: int,
        n_concepts: int,
        n_difficulties: int,
        *,
        d_model: int = 64,
        n_heads: int = 4,
        dropout: float = 0.1,
    ) -> None:
        super().__init__()
        self.d_model = d_model
        self.n_heads = n_heads
        self.head_dim = d_model // n_heads
        if self.head_dim * n_heads != d_model:
            raise ValueError("d_model must be divisible by n_heads.")
        self.question_embedding = nn.Embedding(n_questions, d_model)
        self.concept_embedding = nn.Embedding(n_concepts, d_model)
        self.difficulty_embedding = nn.Embedding(n_difficulties, d_model)
        self.response_embedding = nn.Embedding(3, d_model)
        self.context_encoder = nn.GRU(d_model, d_model, batch_first=True)
        self.start_context = nn.Parameter(torch.zeros(d_model))
        self.query_projection = nn.Linear(d_model, d_model)
        self.key_projection = nn.Linear(d_model, d_model)
        self.value_projection = nn.Linear(d_model, d_model)
        self.output_projection = nn.Linear(d_model, d_model)
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
        self.item_bias = nn.Embedding(n_questions, 1)
        self.head = nn.Sequential(
            nn.Linear(d_model * 2, d_model),
            nn.GELU(),
            nn.Dropout(dropout),
            nn.Linear(d_model, 1),
        )

    def forward(
        self,
        questions: torch.Tensor,
        concepts: torch.Tensor,
        difficulties: torch.Tensor,
        responses: torch.Tensor,
        mask: torch.Tensor,
    ) -> torch.Tensor:
        batch, length = questions.shape
        query = (
            self.question_embedding(questions)
            + self.concept_embedding(concepts)
            + self.difficulty_embedding(difficulties)
        )
        context_input = query + self.response_embedding(responses)
        context, _ = self.context_encoder(context_input)
        key_value = torch.cat(
            [self.start_context.view(1, 1, -1).expand(batch, -1, -1), context],
            dim=1,
        )
        q = self.query_projection(query).view(batch, length, self.n_heads, self.head_dim).transpose(1, 2)
        k = self.key_projection(key_value).view(batch, length + 1, self.n_heads, self.head_dim).transpose(1, 2)
        v = self.value_projection(key_value).view(batch, length + 1, self.n_heads, self.head_dim).transpose(1, 2)
        scores = torch.matmul(q, k.transpose(-2, -1)) / math.sqrt(self.head_dim)
        positions = torch.arange(length, device=questions.device)
        history_positions = torch.arange(length, device=questions.device)
        distance = positions.view(-1, 1) - history_positions.view(1, -1)
        distance = distance.clamp(min=0, max=MAX_RELATIVE_DISTANCE - 1).reshape(-1)
        history_bias = self.relative_bias[distance].reshape(length, length, self.n_heads)
        history_bias = history_bias.permute(2, 0, 1)
        scores[..., 1:] = scores[..., 1:] + history_bias.unsqueeze(0)
        positions_tensor = torch.arange(length, device=questions.device)
        allowed = history_positions.view(1, -1) < positions_tensor.view(-1, 1)
        allowed = allowed.unsqueeze(0).expand(batch, -1, -1)
        start_allowed = torch.ones((batch, length, 1), dtype=torch.bool, device=questions.device)
        attention_mask = ~torch.cat([start_allowed, allowed], dim=2)
        key_padding_mask = ~torch.cat(
            [torch.ones((batch, 1), dtype=torch.bool, device=questions.device), mask],
            dim=1,
        )
        scores = scores.masked_fill(attention_mask.unsqueeze(1), -1e9)
        scores = scores.masked_fill(key_padding_mask[:, None, None, :], -1e9)
        attention = torch.softmax(scores, dim=-1)
        attended = torch.matmul(attention, v)
        attended = attended.transpose(1, 2).reshape(batch, length, self.d_model)
        attended = self.output_projection(attended)
        hidden = self.norm1(query + attended)
        hidden = self.norm2(hidden + self.feed_forward(hidden))
        output = self.head(torch.cat([hidden, query], dim=-1)).squeeze(-1)
        return output + self.item_bias(questions).squeeze(-1)


def _validation_loss(model: nn.Module, sequences: Sequence[SequenceArrays], batch_size: int) -> float:
    model.eval()
    loader = DataLoader(sequences, batch_size=batch_size, shuffle=False, collate_fn=collate_sequences)
    criterion = nn.BCEWithLogitsLoss(reduction="none")
    total_loss = 0.0
    total_count = 0
    with torch.no_grad():
        for batch in loader:
            logits = model(
                batch["questions"],
                batch["concepts"],
                batch["difficulties"],
                batch["responses"],
                batch["mask"],
            )
            losses = criterion(logits, batch["correct"])
            selected = losses[batch["mask"]]
            total_loss += float(selected.sum())
            total_count += int(batch["mask"].sum())
    return total_loss / max(total_count, 1)


def train_neural_model(
    model: nn.Module,
    train_sequences: Sequence[SequenceArrays],
    validation_sequences: Sequence[SequenceArrays],
    *,
    model_name: str,
    epochs: int = 5,
    batch_size: int = 32,
    learning_rate: float = 1e-3,
    weight_decay: float = 1e-5,
    patience: int = 2,
    seed: int = 20261020,
) -> Tuple[nn.Module, Dict[str, Any]]:
    torch.manual_seed(seed)
    np.random.seed(seed)
    loader = DataLoader(
        train_sequences,
        batch_size=batch_size,
        shuffle=True,
        collate_fn=collate_sequences,
    )
    optimizer = torch.optim.AdamW(model.parameters(), lr=learning_rate, weight_decay=weight_decay)
    criterion = nn.BCEWithLogitsLoss(reduction="none")
    history: List[Dict[str, Any]] = []
    best_state = copy.deepcopy(model.state_dict())
    best_loss = float("inf")
    best_epoch = 0
    started = time.perf_counter()
    for epoch in range(1, epochs + 1):
        model.train()
        epoch_loss = 0.0
        epoch_count = 0
        for batch in loader:
            optimizer.zero_grad(set_to_none=True)
            logits = model(
                batch["questions"],
                batch["concepts"],
                batch["difficulties"],
                batch["responses"],
                batch["mask"],
            )
            losses = criterion(logits, batch["correct"])
            selected = losses[batch["mask"]]
            loss = selected.mean()
            loss.backward()
            nn.utils.clip_grad_norm_(model.parameters(), 5.0)
            optimizer.step()
            epoch_loss += float(selected.detach().sum().item())
            epoch_count += int(batch["mask"].sum())
        validation_loss = _validation_loss(model, validation_sequences, batch_size * 2)
        history.append(
            {
                "epoch": epoch,
                "train_log_loss": epoch_loss / max(epoch_count, 1),
                "validation_log_loss": validation_loss,
            }
        )
        if validation_loss < best_loss:
            best_loss = validation_loss
            best_epoch = epoch
            best_state = copy.deepcopy(model.state_dict())
        if epoch - best_epoch >= patience:
            break
    model.load_state_dict(best_state)
    model.eval()
    return model, {
        "model": model_name,
        "best_epoch": best_epoch,
        "best_validation_log_loss": best_loss,
        "epochs_completed": len(history),
        "train_seconds": float(time.perf_counter() - started),
        "history": history,
    }


def predict_neural_model(
    model: nn.Module,
    sequences: Sequence[SequenceArrays],
    *,
    batch_size: int = 64,
) -> pd.Series:
    model.eval()
    loader = DataLoader(sequences, batch_size=batch_size, shuffle=False, collate_fn=collate_sequences)
    ids: List[str] = []
    probabilities: List[np.ndarray] = []
    with torch.no_grad():
        for batch in loader:
            logits = model(
                batch["questions"],
                batch["concepts"],
                batch["difficulties"],
                batch["responses"],
                batch["mask"],
            )
            probs = torch.sigmoid(logits).cpu().numpy()
            mask = batch["mask"].cpu().numpy()
            ids.extend(np.asarray(batch["interaction_ids"], dtype=object)[mask.reshape(-1)].tolist())
            probabilities.append(probs[mask])
    return pd.Series(_clip(np.concatenate(probabilities)), index=ids)

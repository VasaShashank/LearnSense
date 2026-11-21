"""AKT + Concept-Mastery Head model for LearnSense.

This module implements an experimental multi-task knowledge-tracing model that
combines the causal AKT-style sequence encoder with a dedicated concept-mastery
estimation head.

Architecture:
1. Backbone: Causal AKT-style sequence encoder with:
   - Question, concept, and difficulty embeddings
   - Context GRU encoder and causal attention with relative distance bias
   - Rasch-style item bias term
2. Response-Prediction Head:
   - Projects contextual representation to next-item correctness logit
   - Trained with binary cross-entropy against observed student response
3. Concept-Mastery Head:
   - Projects contextual representation to latent concept mastery logits
     for all concepts in the vocabulary
   - Trained with binary cross-entropy against causal ground-truth mastery
     (latent_mastery_primary_before from simulator diagnostics)

Operational Definition of Mastery Target:
The mastery target at step t is defined as the student's true latent concept
mastery immediately prior to responding to item t (`latent_mastery_primary_before`
in [0, 1]). It reflects prior learning updates and time-based forgetting decay.
It does NOT use post-response updates (latent_mastery_primary_after) or any
future student responses, ensuring strict temporal causality.
"""

from __future__ import annotations

import copy
import math
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

import numpy as np
import pandas as pd
import torch
from torch import nn
from torch.utils.data import DataLoader

from src.baselines import PROBABILITY_EPSILON
from src.benchmark_neural import (
    MAX_RELATIVE_DISTANCE,
    START_RESPONSE,
    Vocabulary,
    _clip,
)


@dataclass
class MasterySequenceArrays:
    interaction_ids: np.ndarray
    questions: np.ndarray
    concepts: np.ndarray
    difficulties: np.ndarray
    previous_responses: np.ndarray
    correct: np.ndarray
    mastery_targets: np.ndarray

    def __len__(self) -> int:
        return len(self.correct)


def build_mastery_sequences(
    targets: pd.DataFrame,
    vocabulary: Vocabulary,
    diagnostics: Optional[pd.DataFrame] = None,
) -> List[MasterySequenceArrays]:
    """Builds learner sequences including causal ground-truth mastery labels.

    Preserves strict chronological ordering within learner:
    sorts by student_id, sequence_index, timestamp_utc.
    """
    df = targets.copy()
    if diagnostics is not None and "latent_mastery_primary_before" in diagnostics.columns:
        diag_cols = ["interaction_id", "latent_mastery_primary_before"]
        df = df.merge(
            diagnostics[diag_cols],
            on="interaction_id",
            how="left",
            validate="one_to_one",
        )
    if "latent_mastery_primary_before" not in df.columns:
        df["latent_mastery_primary_before"] = 0.0

    df = df.sort_values(
        by=["student_id", "sequence_index", "timestamp_utc"],
        kind="mergesort",
    )
    sequences: List[MasterySequenceArrays] = []
    for _, group in df.groupby("student_id", sort=False):
        questions = (
            group["question_id"]
            .astype(str)
            .map(vocabulary.question_to_index)
            .fillna(0)
            .to_numpy(dtype=np.int64)
        )
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

        mastery_vals = (
            group["latent_mastery_primary_before"].fillna(0.0).to_numpy(dtype=np.float32)
        )

        sequences.append(
            MasterySequenceArrays(
                interaction_ids=group["interaction_id"].astype(str).to_numpy(),
                questions=questions,
                concepts=concepts,
                difficulties=difficulties,
                previous_responses=previous,
                correct=correct,
                mastery_targets=mastery_vals,
            )
        )
    return sequences


def collate_mastery_sequences(
    sequences: Sequence[MasterySequenceArrays],
) -> Dict[str, Any]:
    """Collates a batch of MasterySequenceArrays with padding."""
    max_len = max(len(sequence) for sequence in sequences)
    batch = len(sequences)
    questions = torch.zeros((batch, max_len), dtype=torch.long)
    concepts = torch.zeros((batch, max_len), dtype=torch.long)
    difficulties = torch.zeros((batch, max_len), dtype=torch.long)
    responses = torch.full((batch, max_len), START_RESPONSE, dtype=torch.long)
    correct = torch.zeros((batch, max_len), dtype=torch.float32)
    mastery_targets = torch.zeros((batch, max_len), dtype=torch.float32)
    mask = torch.zeros((batch, max_len), dtype=torch.bool)
    interaction_ids: List[str] = []

    for row, sequence in enumerate(sequences):
        length = len(sequence)
        questions[row, :length] = torch.from_numpy(sequence.questions)
        concepts[row, :length] = torch.from_numpy(sequence.concepts)
        difficulties[row, :length] = torch.from_numpy(sequence.difficulties)
        responses[row, :length] = torch.from_numpy(sequence.correct.astype(np.int64))
        correct[row, :length] = torch.from_numpy(sequence.correct.astype(np.float32))
        mastery_targets[row, :length] = torch.from_numpy(sequence.mastery_targets)
        mask[row, :length] = True
        interaction_ids.extend(sequence.interaction_ids.tolist())
        interaction_ids.extend([""] * (max_len - length))

    return {
        "questions": questions,
        "concepts": concepts,
        "difficulties": difficulties,
        "responses": responses,
        "correct": correct,
        "mastery_targets": mastery_targets,
        "mask": mask,
        "interaction_ids": interaction_ids,
    }


class AKTMasteryHeadModel(nn.Module):
    """Adapted AKT-style sequence model with dedicated Concept-Mastery Head.

    Emits:
    1. response_logits: [batch, seq_len] correctness logit for item at step t.
    2. primary_mastery_logits: [batch, seq_len] mastery logit for the tested concept at step t.
    3. mastery_all_logits: [batch, seq_len, n_concepts] mastery logits across all concepts at step t.
    """

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
        self.n_concepts = n_concepts
        self.head_dim = d_model // n_heads
        if self.head_dim * n_heads != d_model:
            raise ValueError("d_model must be divisible by n_heads.")

        # Embeddings
        self.question_embedding = nn.Embedding(n_questions, d_model)
        self.concept_embedding = nn.Embedding(n_concepts, d_model)
        self.difficulty_embedding = nn.Embedding(n_difficulties, d_model)
        self.response_embedding = nn.Embedding(3, d_model)

        # Causal context encoder
        self.context_encoder = nn.GRU(d_model, d_model, batch_first=True)
        self.start_context = nn.Parameter(torch.zeros(d_model))

        # Causal attention projections
        self.query_projection = nn.Linear(d_model, d_model)
        self.key_projection = nn.Linear(d_model, d_model)
        self.value_projection = nn.Linear(d_model, d_model)
        self.output_projection = nn.Linear(d_model, d_model)

        # Relative position bias & residual feed-forward
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

        # Head 1: Response-prediction head
        self.response_head = nn.Sequential(
            nn.Linear(d_model * 2, d_model),
            nn.GELU(),
            nn.Dropout(dropout),
            nn.Linear(d_model, 1),
        )

        # Head 2: Concept-mastery estimation head
        self.mastery_proj = nn.Sequential(
            nn.Linear(d_model, d_model),
            nn.GELU(),
            nn.Dropout(dropout),
        )
        self.mastery_head = nn.Linear(d_model, n_concepts)

    def forward(
        self,
        questions: torch.Tensor,
        concepts: torch.Tensor,
        difficulties: torch.Tensor,
        responses: torch.Tensor,
        mask: torch.Tensor,
    ) -> Tuple[torch.Tensor, torch.Tensor, torch.Tensor]:
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

        # Strict causal masking: step i only attends to start_context and past steps < i
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

        # 1. Response-prediction output
        response_output = self.response_head(torch.cat([hidden, query], dim=-1)).squeeze(-1)
        response_logits = response_output + self.item_bias(questions).squeeze(-1)

        # 2. Concept-mastery output across all concepts
        mastery_feat = self.mastery_proj(hidden)
        mastery_all_logits = self.mastery_head(mastery_feat)  # [batch, length, n_concepts]

        # 3. Gather primary concept logit tested at each step
        primary_mastery_logits = torch.gather(
            mastery_all_logits, 2, concepts.unsqueeze(-1)
        ).squeeze(-1)  # [batch, length]

        return response_logits, primary_mastery_logits, mastery_all_logits

    def predict_student_concept_mastery(
        self,
        questions: torch.Tensor,
        concepts: torch.Tensor,
        difficulties: torch.Tensor,
        responses: torch.Tensor,
        mask: torch.Tensor,
        vocabulary: Vocabulary,
    ) -> List[Dict[str, float]]:
        """Computes current concept-mastery estimates (percentages in [0, 1]) for all learners.

        Returns a list of dictionaries mapping concept_id -> mastery_probability
        evaluated at each learner's final active sequence position.
        """
        self.eval()
        with torch.no_grad():
            _, _, mastery_all_logits = self.forward(
                questions, concepts, difficulties, responses, mask
            )
            probs = torch.sigmoid(mastery_all_logits).cpu().numpy()
            lengths = mask.sum(dim=1).cpu().numpy() - 1
            lengths = np.clip(lengths, 0, None)

            index_to_concept = {
                idx: cid for cid, idx in vocabulary.concept_to_index.items()
            }
            results: List[Dict[str, float]] = []
            for b in range(len(lengths)):
                step_idx = int(lengths[b])
                student_probs = probs[b, step_idx]  # shape: [n_concepts]
                concept_map: Dict[str, float] = {}
                for idx, cid in index_to_concept.items():
                    concept_map[cid] = float(np.clip(student_probs[idx], PROBABILITY_EPSILON, 1.0 - PROBABILITY_EPSILON))
                results.append(concept_map)
            return results


def _validation_multitask_loss(
    model: AKTMasteryHeadModel,
    sequences: Sequence[MasterySequenceArrays],
    batch_size: int,
    *,
    response_weight: float = 1.0,
    mastery_weight: float = 0.5,
) -> Dict[str, float]:
    model.eval()
    loader = DataLoader(
        sequences,
        batch_size=batch_size,
        shuffle=False,
        collate_fn=collate_mastery_sequences,
    )
    criterion = nn.BCEWithLogitsLoss(reduction="none")
    total_resp_loss = 0.0
    total_mast_loss = 0.0
    total_count = 0
    with torch.no_grad():
        for batch in loader:
            resp_logits, mast_logits, _ = model(
                batch["questions"],
                batch["concepts"],
                batch["difficulties"],
                batch["responses"],
                batch["mask"],
            )
            r_losses = criterion(resp_logits, batch["correct"])
            m_losses = criterion(mast_logits, batch["mastery_targets"])

            sel_r = r_losses[batch["mask"]]
            sel_m = m_losses[batch["mask"]]
            total_resp_loss += float(sel_r.sum())
            total_mast_loss += float(sel_m.sum())
            total_count += int(batch["mask"].sum())

    n = max(total_count, 1)
    mean_resp = total_resp_loss / n
    mean_mast = total_mast_loss / n
    total_loss = response_weight * mean_resp + mastery_weight * mean_mast
    return {
        "val_total_loss": total_loss,
        "val_response_loss": mean_resp,
        "val_mastery_loss": mean_mast,
    }


def train_akt_mastery_model(
    model: AKTMasteryHeadModel,
    train_sequences: Sequence[MasterySequenceArrays],
    validation_sequences: Sequence[MasterySequenceArrays],
    *,
    model_name: str = "akt_concept_mastery_head",
    epochs: int = 5,
    batch_size: int = 32,
    learning_rate: float = 1e-3,
    weight_decay: float = 1e-5,
    patience: int = 2,
    seed: int = 20261020,
    response_weight: float = 1.0,
    mastery_weight: float = 0.5,
) -> Tuple[AKTMasteryHeadModel, Dict[str, Any]]:
    """Trains the AKTMasteryHeadModel with multi-task supervision."""
    torch.manual_seed(seed)
    np.random.seed(seed)
    loader = DataLoader(
        train_sequences,
        batch_size=batch_size,
        shuffle=True,
        collate_fn=collate_mastery_sequences,
    )
    optimizer = torch.optim.AdamW(
        model.parameters(), lr=learning_rate, weight_decay=weight_decay
    )
    criterion = nn.BCEWithLogitsLoss(reduction="none")
    history: List[Dict[str, Any]] = []
    best_state = copy.deepcopy(model.state_dict())
    best_loss = float("inf")
    best_epoch = 0
    started = time.perf_counter()

    for epoch in range(1, epochs + 1):
        model.train()
        epoch_resp_loss = 0.0
        epoch_mast_loss = 0.0
        epoch_count = 0
        for batch in loader:
            optimizer.zero_grad(set_to_none=True)
            resp_logits, mast_logits, _ = model(
                batch["questions"],
                batch["concepts"],
                batch["difficulties"],
                batch["responses"],
                batch["mask"],
            )
            r_losses = criterion(resp_logits, batch["correct"])
            m_losses = criterion(mast_logits, batch["mastery_targets"])

            sel_r = r_losses[batch["mask"]]
            sel_m = m_losses[batch["mask"]]

            loss = response_weight * sel_r.mean()
            if mastery_weight > 0:
                loss = loss + mastery_weight * sel_m.mean()

            loss.backward()
            nn.utils.clip_grad_norm_(model.parameters(), 5.0)
            optimizer.step()

            epoch_resp_loss += float(sel_r.detach().sum().item())
            epoch_mast_loss += float(sel_m.detach().sum().item())
            epoch_count += int(batch["mask"].sum())

        val_metrics = _validation_multitask_loss(
            model,
            validation_sequences,
            batch_size * 2,
            response_weight=response_weight,
            mastery_weight=mastery_weight,
        )
        n_ep = max(epoch_count, 1)
        history.append(
            {
                "epoch": epoch,
                "train_response_log_loss": epoch_resp_loss / n_ep,
                "train_mastery_log_loss": epoch_mast_loss / n_ep,
                **val_metrics,
            }
        )

        monitor_loss = val_metrics["val_total_loss"]
        if monitor_loss < best_loss:
            best_loss = monitor_loss
            best_epoch = epoch
            best_state = copy.deepcopy(model.state_dict())
        if epoch - best_epoch >= patience:
            break

    model.load_state_dict(best_state)
    model.eval()
    return model, {
        "model": model_name,
        "best_epoch": best_epoch,
        "best_validation_loss": best_loss,
        "epochs_completed": len(history),
        "train_seconds": float(time.perf_counter() - started),
        "response_weight": response_weight,
        "mastery_weight": mastery_weight,
        "history": history,
    }


def predict_akt_mastery_model(
    model: AKTMasteryHeadModel,
    sequences: Sequence[MasterySequenceArrays],
    *,
    batch_size: int = 64,
) -> Tuple[pd.Series, pd.Series]:
    """Generates aligned predictions for both response correctness and concept mastery.

    Returns:
    - response_probs: pd.Series of P(correct) in [0, 1] indexed by interaction_id.
    - mastery_probs: pd.Series of P(mastery_primary) in [0, 1] indexed by interaction_id.
    """
    model.eval()
    loader = DataLoader(
        sequences,
        batch_size=batch_size,
        shuffle=False,
        collate_fn=collate_mastery_sequences,
    )
    ids: List[str] = []
    response_probs: List[np.ndarray] = []
    mastery_probs: List[np.ndarray] = []

    with torch.no_grad():
        for batch in loader:
            resp_logits, mast_logits, _ = model(
                batch["questions"],
                batch["concepts"],
                batch["difficulties"],
                batch["responses"],
                batch["mask"],
            )
            r_p = torch.sigmoid(resp_logits).cpu().numpy()
            m_p = torch.sigmoid(mast_logits).cpu().numpy()
            mask_np = batch["mask"].cpu().numpy()

            ids.extend(
                np.asarray(batch["interaction_ids"], dtype=object)[
                    mask_np.reshape(-1)
                ].tolist()
            )
            response_probs.append(r_p[mask_np])
            mastery_probs.append(m_p[mask_np])

    resp_series = pd.Series(
        _clip(np.concatenate(response_probs)), index=ids, name="p_response"
    )
    mast_series = pd.Series(
        _clip(np.concatenate(mastery_probs)), index=ids, name="p_mastery"
    )
    return resp_series, mast_series

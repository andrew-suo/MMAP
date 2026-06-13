"""Weak-label voting utilities for evaluation samples without ground truth.

The helpers in this module deliberately keep weak votes separate from real
metrics. Majority votes from evaluator/optimizer models are useful for analysis,
sampling, and triage, but they must not replace ground-truth-backed metrics.
"""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass
from typing import Any, Callable, Mapping, Protocol


INVALID_VOTE = "__invalid__"
DEFAULT_VOTE_ROUNDS = 3


@dataclass(slots=True)
class EvalVoteResult:
    """Result of independent evaluator votes for a single sample.

    Attributes:
        votes: Count of normalized vote statuses.
        majority_status: The majority status when one exists, otherwise ``None``.
        confidence: Fraction of votes held by ``majority_status``. For a full
            three-way conflict this is ``1 / 3`` and ``majority_status`` is
            ``None``.
        raw_judgements: Raw model responses, parsed JSON objects, or fallback
            payloads for invalid responses.
        model_ids: Model identifiers used for each vote.
        is_ground_truth_backed: Always defaults to ``False`` for weak votes.
    """

    votes: dict[str, int]
    majority_status: str | None
    confidence: float
    raw_judgements: list[Any]
    model_ids: list[str]
    is_ground_truth_backed: bool = False


class EvalModel(Protocol):
    """Protocol for objects that can provide evaluator judgements."""

    def judge(self, sample: Mapping[str, Any], *, round_index: int) -> Any:
        """Return an evaluator judgement for ``sample``."""


def parse_vote_judgement(judgement: Any) -> tuple[str, Any]:
    """Parse a model judgement into a normalized vote status and raw payload.

    JSON strings are expected to contain one of ``vote``, ``status``,
    ``judgement``, ``judgment``, ``label``, or ``result``. Invalid JSON or JSON
    without a vote-like field falls back to the ``INVALID_VOTE`` sentinel so the
    failed vote is visible to downstream analysis instead of being silently
    dropped.
    """

    raw_payload = judgement
    parsed = judgement

    if isinstance(judgement, str):
        try:
            parsed = json.loads(judgement)
            raw_payload = parsed
        except json.JSONDecodeError:
            return INVALID_VOTE, {"raw": judgement, "parse_error": "invalid_json"}

    if isinstance(parsed, Mapping):
        for key in ("vote", "status", "judgement", "judgment", "label", "result"):
            value = parsed.get(key)
            if value is not None:
                return normalize_vote(value), raw_payload
        return INVALID_VOTE, {"raw": raw_payload, "parse_error": "missing_vote"}

    if parsed is None:
        return INVALID_VOTE, {"raw": parsed, "parse_error": "missing_vote"}

    return normalize_vote(parsed), raw_payload


def normalize_vote(value: Any) -> str:
    """Convert an arbitrary vote value into a stable status string."""

    return str(value).strip().lower() or INVALID_VOTE


def majority_vote(
    judgements: list[Any],
    *,
    model_ids: list[str] | None = None,
    is_ground_truth_backed: bool = False,
) -> EvalVoteResult:
    """Aggregate independent judgements into a weak-label vote result."""

    statuses: list[str] = []
    raw_judgements: list[Any] = []
    for judgement in judgements:
        status, raw_payload = parse_vote_judgement(judgement)
        statuses.append(status)
        raw_judgements.append(raw_payload)

    vote_counter = Counter(statuses)
    total_votes = len(statuses)
    if total_votes == 0:
        majority_status = None
        confidence = 0.0
    else:
        most_common = vote_counter.most_common()
        top_status, top_count = most_common[0]
        has_tie = len(most_common) > 1 and most_common[1][1] == top_count
        majority_status = None if has_tie else top_status
        confidence = top_count / total_votes

    return EvalVoteResult(
        votes=dict(vote_counter),
        majority_status=majority_status,
        confidence=confidence,
        raw_judgements=raw_judgements,
        model_ids=list(model_ids or []),
        is_ground_truth_backed=is_ground_truth_backed,
    )


def collect_eval_votes(
    sample: Mapping[str, Any],
    eval_model: EvalModel | Callable[..., Any],
    *,
    rounds: int = DEFAULT_VOTE_ROUNDS,
    model_id: str | None = None,
) -> EvalVoteResult:
    """Run independent evaluator judgements for a sample without ground truth.

    Samples that already contain ground truth should be evaluated by real GT
    metrics instead. This function raises ``ValueError`` for such samples to
    prevent weak votes from accidentally replacing GT-backed accuracy.
    """

    if has_ground_truth(sample):
        raise ValueError("Weak voting is only for samples without ground truth")

    judgements: list[Any] = []
    model_ids: list[str] = []
    for round_index in range(rounds):
        judgements.append(_call_eval_model(eval_model, sample, round_index=round_index))
        model_ids.append(model_id or getattr(eval_model, "model_id", eval_model.__class__.__name__))

    return majority_vote(judgements, model_ids=model_ids, is_ground_truth_backed=False)


def has_ground_truth(sample: Mapping[str, Any]) -> bool:
    """Return whether a sample contains a non-empty ground-truth value."""

    for key in ("ground_truth", "gt", "expected", "label"):
        if key in sample and sample[key] is not None:
            return True
    return False


def _call_eval_model(
    eval_model: EvalModel | Callable[..., Any],
    sample: Mapping[str, Any],
    *,
    round_index: int,
) -> Any:
    if hasattr(eval_model, "judge"):
        return eval_model.judge(sample, round_index=round_index)  # type: ignore[union-attr]
    return eval_model(sample, round_index=round_index)

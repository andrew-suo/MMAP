"""Evaluation metrics that keep ground-truth and weak-vote signals separate."""

from __future__ import annotations

from typing import Any, Iterable, Mapping

from .voting import EvalVoteResult


def compute_evaluation_metrics(records: Iterable[Mapping[str, Any]]) -> dict[str, float | None]:
    """Compute GT accuracy separately from weak vote agreement.

    ``gt_accuracy`` is based only on records containing explicit ground-truth
    correctness. ``weak_vote_agreement`` is based only on non-GT-backed
    ``EvalVoteResult`` objects and reports their average majority confidence.
    """

    gt_total = 0
    gt_correct = 0
    weak_total = 0
    weak_confidence_sum = 0.0

    for record in records:
        if "gt_correct" in record and record["gt_correct"] is not None:
            gt_total += 1
            gt_correct += int(bool(record["gt_correct"]))

        vote_result = record.get("vote_result")
        if isinstance(vote_result, EvalVoteResult) and not vote_result.is_ground_truth_backed:
            weak_total += 1
            weak_confidence_sum += vote_result.confidence

    return {
        "gt_accuracy": (gt_correct / gt_total) if gt_total else None,
        "weak_vote_agreement": (weak_confidence_sum / weak_total) if weak_total else None,
    }

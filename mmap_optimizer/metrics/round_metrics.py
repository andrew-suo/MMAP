from __future__ import annotations

from dataclasses import dataclass, field

from mmap_optimizer.evaluation.evaluator import EvaluationRecord


@dataclass
class RoundMetrics:
    id: str
    round_id: str
    batch_accuracy: float
    dynamic_validation_raw_accuracy: float | None
    dynamic_validation_weighted_accuracy: float | None
    schema_valid_rate: float
    format_error_rate: float
    parse_error_rate: float
    draft_count: int = 0
    candidate_count: int = 0
    accepted_count: int = 0
    rejected_count: int = 0
    toxic_count: int = 0
    ineffective_count: int = 0
    extra: dict = field(default_factory=dict)


def _accuracy(evals: list[EvaluationRecord]) -> float:
    if not evals:
        return 0.0
    return sum(1 for e in evals if e.overall_status == "correct") / len(evals)


def compute_round_metrics(round_id: str, batch_evals: list[EvaluationRecord], dynamic_validation_evals: list[EvaluationRecord] | None = None) -> RoundMetrics:
    schema_valid_rate = sum(1 for e in batch_evals if e.schema_valid) / len(batch_evals) if batch_evals else 0.0
    parse_error_rate = sum(1 for e in batch_evals if e.overall_status == "parse_error") / len(batch_evals) if batch_evals else 0.0
    schema_error_rate = sum(1 for e in batch_evals if e.overall_status == "schema_error") / len(batch_evals) if batch_evals else 0.0
    dval_acc = _accuracy(dynamic_validation_evals or []) if dynamic_validation_evals is not None else None
    return RoundMetrics(
        id=f"metrics_{round_id}", round_id=round_id, batch_accuracy=_accuracy(batch_evals),
        dynamic_validation_raw_accuracy=dval_acc, dynamic_validation_weighted_accuracy=dval_acc,
        schema_valid_rate=schema_valid_rate, format_error_rate=schema_error_rate, parse_error_rate=parse_error_rate,
    )

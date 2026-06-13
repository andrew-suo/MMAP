from __future__ import annotations

from dataclasses import dataclass, field

from mmap_optimizer.metrics.round_metrics import RoundMetrics


@dataclass
class RoundMetricTrendPoint:
    round_id: str
    previous_round_id: str | None
    batch_accuracy: float
    batch_accuracy_delta: float | None
    dynamic_validation_accuracy: float | None
    dynamic_validation_accuracy_delta: float | None
    schema_valid_rate: float
    schema_valid_rate_delta: float | None
    analysis_judgement_match_rate: float
    analysis_judgement_match_rate_delta: float | None
    accepted_count: int
    rejected_count: int
    toxic_count: int
    merge_input_count: int
    merge_output_count: int
    merge_conflict_count: int
    merge_duplicate_count: int
    extraction_regressed: bool = False
    dynamic_validation_regressed: bool = False
    analysis_regressed: bool = False
    notes: list[str] = field(default_factory=list)


@dataclass
class MetricsTrend:
    id: str
    round_count: int
    points: list[RoundMetricTrendPoint] = field(default_factory=list)
    best_batch_round_id: str | None = None
    best_batch_accuracy: float | None = None
    best_dynamic_validation_round_id: str | None = None
    best_dynamic_validation_accuracy: float | None = None
    first_batch_accuracy: float | None = None
    final_batch_accuracy: float | None = None
    batch_accuracy_delta_total: float | None = None
    first_dynamic_validation_accuracy: float | None = None
    final_dynamic_validation_accuracy: float | None = None
    dynamic_validation_accuracy_delta_total: float | None = None
    total_accepted_patches: int = 0
    total_rejected_patches: int = 0
    total_toxic_patches: int = 0
    total_fewshot_replacements: int = 0
    best_fewshot_accuracy_delta: float = 0.0
    final_fewshot_slot_count: int = 0
    total_merge_conflicts: int = 0
    total_merge_duplicates: int = 0
    regression_round_ids: list[str] = field(default_factory=list)
    analysis_regression_round_ids: list[str] = field(default_factory=list)


def _delta(current: float | None, previous: float | None) -> float | None:
    if current is None or previous is None:
        return None
    return current - previous


def _is_negative_delta(value: float | None, *, min_regression_delta: float) -> bool:
    return value is not None and value < -abs(min_regression_delta)


def build_metrics_trend(metrics_records: list[RoundMetrics], *, min_regression_delta: float = 1e-9) -> MetricsTrend:
    """Build a run-level trend report from per-round metrics.

    The report intentionally uses a configurable epsilon so tiny floating-point
    noise is not treated as a real regression. Dynamic-validation regressions
    are tracked separately from optimization-batch regressions because the
    validation sample changes every round by design.
    """

    trend = MetricsTrend(id="metrics_trend", round_count=len(metrics_records))
    previous: RoundMetrics | None = None
    for metrics in metrics_records:
        batch_delta = _delta(metrics.batch_accuracy, previous.batch_accuracy if previous else None)
        dval_delta = _delta(metrics.dynamic_validation_raw_accuracy, previous.dynamic_validation_raw_accuracy if previous else None)
        schema_delta = _delta(metrics.schema_valid_rate, previous.schema_valid_rate if previous else None)
        analysis_delta = _delta(
            metrics.analysis_judgement_match_rate,
            previous.analysis_judgement_match_rate if previous else None,
        )
        point = RoundMetricTrendPoint(
            round_id=metrics.round_id,
            previous_round_id=previous.round_id if previous else None,
            batch_accuracy=metrics.batch_accuracy,
            batch_accuracy_delta=batch_delta,
            dynamic_validation_accuracy=metrics.dynamic_validation_raw_accuracy,
            dynamic_validation_accuracy_delta=dval_delta,
            schema_valid_rate=metrics.schema_valid_rate,
            schema_valid_rate_delta=schema_delta,
            analysis_judgement_match_rate=metrics.analysis_judgement_match_rate,
            analysis_judgement_match_rate_delta=analysis_delta,
            accepted_count=metrics.accepted_count,
            rejected_count=metrics.rejected_count,
            toxic_count=metrics.toxic_count,
            merge_input_count=metrics.merge_input_count,
            merge_output_count=metrics.merge_output_count,
            merge_conflict_count=metrics.merge_conflict_count,
            merge_duplicate_count=metrics.merge_duplicate_count,
            extraction_regressed=_is_negative_delta(batch_delta, min_regression_delta=min_regression_delta),
            dynamic_validation_regressed=_is_negative_delta(dval_delta, min_regression_delta=min_regression_delta),
            analysis_regressed=_is_negative_delta(analysis_delta, min_regression_delta=min_regression_delta),
        )
        if point.extraction_regressed:
            point.notes.append("optimization batch accuracy decreased")
        if point.dynamic_validation_regressed:
            point.notes.append("dynamic validation accuracy decreased on the sampled validation batch")
        if point.analysis_regressed:
            point.notes.append("analysis judgement-match rate decreased")
        trend.points.append(point)
        previous = metrics

    if not metrics_records:
        return trend

    first = metrics_records[0]
    final = metrics_records[-1]
    trend.first_batch_accuracy = first.batch_accuracy
    trend.final_batch_accuracy = final.batch_accuracy
    trend.batch_accuracy_delta_total = final.batch_accuracy - first.batch_accuracy
    first_dval = next((m.dynamic_validation_raw_accuracy for m in metrics_records if m.dynamic_validation_raw_accuracy is not None), None)
    final_dval = next((m.dynamic_validation_raw_accuracy for m in reversed(metrics_records) if m.dynamic_validation_raw_accuracy is not None), None)
    trend.first_dynamic_validation_accuracy = first_dval
    trend.final_dynamic_validation_accuracy = final_dval
    trend.dynamic_validation_accuracy_delta_total = _delta(final_dval, first_dval)
    best_batch = max(metrics_records, key=lambda m: m.batch_accuracy)
    trend.best_batch_round_id = best_batch.round_id
    trend.best_batch_accuracy = best_batch.batch_accuracy
    dval_records = [m for m in metrics_records if m.dynamic_validation_raw_accuracy is not None]
    if dval_records:
        best_dval = max(dval_records, key=lambda m: m.dynamic_validation_raw_accuracy or 0.0)
        trend.best_dynamic_validation_round_id = best_dval.round_id
        trend.best_dynamic_validation_accuracy = best_dval.dynamic_validation_raw_accuracy
    trend.total_accepted_patches = sum(m.accepted_count for m in metrics_records)
    trend.total_rejected_patches = sum(m.rejected_count for m in metrics_records)
    trend.total_toxic_patches = sum(m.toxic_count for m in metrics_records)
    trend.total_fewshot_replacements = sum(m.fewshot_replacement_count for m in metrics_records)
    trend.best_fewshot_accuracy_delta = max((m.fewshot_accuracy_delta for m in metrics_records), default=0.0)
    trend.final_fewshot_slot_count = final.fewshot_slot_count_after
    trend.total_merge_conflicts = sum(m.merge_conflict_count for m in metrics_records)
    trend.total_merge_duplicates = sum(m.merge_duplicate_count for m in metrics_records)
    trend.regression_round_ids = [p.round_id for p in trend.points if p.extraction_regressed or p.dynamic_validation_regressed]
    trend.analysis_regression_round_ids = [p.round_id for p in trend.points if p.analysis_regressed]
    return trend

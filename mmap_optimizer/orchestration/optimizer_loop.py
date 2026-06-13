from __future__ import annotations

from dataclasses import dataclass, field

from mmap_optimizer.core.config import OptimizerConfig
from mmap_optimizer.metrics.round_metrics import RoundMetrics
from mmap_optimizer.metrics.trend import MetricsTrend, build_metrics_trend
from mmap_optimizer.storage.json_store import JsonStore
from .records import OptimizationRound
from .run_state import RunState, RunStateStore
from .round_runner import OptimizerState, RoundRunner


@dataclass
class OptimizationRunSummary:
    id: str
    status: str
    planned_round_count: int
    completed_round_count: int = 0
    round_ids: list[str] = field(default_factory=list)
    final_extraction_prompt_version_id: str | None = None
    final_analysis_prompt_version_id: str | None = None
    first_batch_accuracy: float | None = None
    final_batch_accuracy: float | None = None
    best_batch_accuracy: float | None = None
    first_dynamic_validation_accuracy: float | None = None
    final_dynamic_validation_accuracy: float | None = None
    total_accepted_patches: int = 0
    total_rejected_patches: int = 0
    total_toxic_patches: int = 0
    total_compression_accepts: int = 0
    total_fewshot_accepts: int = 0
    stopped_reason: str | None = None
    metrics_trend_id: str | None = None
    regression_round_ids: list[str] = field(default_factory=list)
    analysis_regression_round_ids: list[str] = field(default_factory=list)
    batch_accuracy_delta_total: float | None = None
    dynamic_validation_accuracy_delta_total: float | None = None


class OptimizerLoop:
    """Runs the configured serial optimization lifecycle.

    The loop intentionally does not early-stop when a text round has no accepted
    extraction patch: analysis evolution, sampling statistics, compression, and
    later few-shot rounds still need deterministic round accounting.
    """

    def __init__(self, *, runner: RoundRunner, store: JsonStore, config: OptimizerConfig | None = None):
        self.runner = runner
        self.store = store
        self.config = config or runner.config
        self.run_state_store = RunStateStore(store)

    def run(self, state: OptimizerState, *, start_round: int = 1, max_rounds: int | None = None) -> tuple[list[OptimizationRound], list[RoundMetrics], OptimizationRunSummary]:
        planned_rounds = max_rounds if max_rounds is not None else self._default_round_count()
        if planned_rounds < 1:
            raise ValueError("planned round count must be at least 1")
        summary = OptimizationRunSummary(id="optimization_run_summary", status="RUNNING", planned_round_count=planned_rounds)
        rounds: list[OptimizationRound] = []
        metrics_records: list[RoundMetrics] = []
        self.store.write_json("run_summary.json", summary)
        self.run_state_store.save(RunState(run_id=summary.id, iteration=start_round - 1, stage="initialized", completed_round_ids=[]))

        for offset in range(planned_rounds):
            round_index = start_round + offset
            self.run_state_store.save(RunState(run_id=summary.id, iteration=round_index, stage="round_started", completed_round_ids=[record.id for record in rounds]))
            round_record, metrics = self.runner.run_round(state, round_index=round_index)
            rounds.append(round_record)
            metrics_records.append(metrics)
            self._accumulate(summary, round_record, metrics)
            summary.completed_round_count = len(rounds)
            summary.round_ids = [record.id for record in rounds]
            summary.final_extraction_prompt_version_id = state.active_extraction_prompt.id
            summary.final_analysis_prompt_version_id = state.active_analysis_prompt.id
            self._write_trend_and_summary(summary, metrics_records)
            self.run_state_store.save(RunState(run_id=summary.id, iteration=round_index, stage="round_completed", completed_round_ids=summary.round_ids))

        summary.status = "COMPLETED"
        summary.stopped_reason = "PLANNED_ROUNDS_COMPLETED"
        self._write_trend_and_summary(summary, metrics_records)
        self.run_state_store.save(RunState(run_id=summary.id, iteration=start_round + planned_rounds - 1, stage="completed", completed_round_ids=summary.round_ids))
        return rounds, metrics_records, summary

    def _write_trend_and_summary(self, summary: OptimizationRunSummary, metrics_records: list[RoundMetrics]) -> MetricsTrend:
        trend = build_metrics_trend(metrics_records)
        summary.metrics_trend_id = trend.id
        summary.regression_round_ids = trend.regression_round_ids
        summary.analysis_regression_round_ids = trend.analysis_regression_round_ids
        summary.batch_accuracy_delta_total = trend.batch_accuracy_delta_total
        summary.dynamic_validation_accuracy_delta_total = trend.dynamic_validation_accuracy_delta_total
        self.store.write_json("metrics_trend.json", trend)
        self.store.write_json("run_summary.json", summary)
        return trend

    def _default_round_count(self) -> int:
        fewshot_rounds = self.config.fewshot_max_rounds if self.config.fewshot_enabled else 0
        return self.config.max_text_rounds + fewshot_rounds

    def _accumulate(self, summary: OptimizationRunSummary, round_record: OptimizationRound, metrics: RoundMetrics) -> None:
        if summary.first_batch_accuracy is None:
            summary.first_batch_accuracy = metrics.batch_accuracy
        summary.final_batch_accuracy = metrics.batch_accuracy
        summary.best_batch_accuracy = max(summary.best_batch_accuracy if summary.best_batch_accuracy is not None else metrics.batch_accuracy, metrics.batch_accuracy)
        if summary.first_dynamic_validation_accuracy is None and metrics.dynamic_validation_raw_accuracy is not None:
            summary.first_dynamic_validation_accuracy = metrics.dynamic_validation_raw_accuracy
        if metrics.dynamic_validation_raw_accuracy is not None:
            summary.final_dynamic_validation_accuracy = metrics.dynamic_validation_raw_accuracy
        summary.total_accepted_patches += metrics.accepted_count
        summary.total_rejected_patches += metrics.rejected_count
        summary.total_toxic_patches += metrics.toxic_count
        summary.total_compression_accepts += 1 if metrics.compression_accepted else 0
        summary.total_fewshot_accepts += 1 if metrics.fewshot_accepted else 0


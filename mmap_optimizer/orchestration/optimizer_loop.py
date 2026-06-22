from __future__ import annotations

import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

from mmap_optimizer.core.config import OptimizerConfig
from mmap_optimizer.dataset.sample import SampleState
from mmap_optimizer.logging import get_logger, log_stage
from mmap_optimizer.metrics.round_metrics import RoundMetrics
from mmap_optimizer.metrics.trend import MetricsTrend, build_metrics_trend
from mmap_optimizer.prompt.version import PromptVersion
from mmap_optimizer.storage.json_store import JsonStore
from .checkpoint import OptimizerCheckpoint
from .records import OptimizationRound
from .round_runner import OptimizerState, RoundRunner

logger = get_logger(__name__)


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

    def __init__(self, *, runner: RoundRunner, store: JsonStore, config: OptimizerConfig | None = None, resume: bool = False):
        self.runner = runner
        self.store = store
        self.config = config or runner.config
        self.resume = resume

    def run(self, state: OptimizerState, *, start_round: int = 1, max_rounds: int | None = None) -> tuple[list[OptimizationRound], list[RoundMetrics], OptimizationRunSummary]:
        planned_rounds = max_rounds if max_rounds is not None else self._default_round_count()
        if planned_rounds < 1:
            raise ValueError("planned round count must be at least 1")
        effective_start = start_round
        if self.resume:
            existing = self._load_existing_checkpoint()
            if existing is not None:
                effective_start = existing.round_index + 1
                self._restore_state_from_checkpoint(state, existing)
        summary = OptimizationRunSummary(id="optimization_run_summary", status="RUNNING", planned_round_count=planned_rounds)
        rounds: list[OptimizationRound] = []
        metrics_records: list[RoundMetrics] = []
        global_iteration_counter = 0
        self.store.write_json("run_summary.json", summary)
        log_stage(logger, "optimizer_start", planned_rounds=planned_rounds, start_round=effective_start, resume=self.resume)

        try:
            for offset in range(planned_rounds):
                round_index = effective_start + offset
                round_start_time = time.perf_counter()
                log_stage(logger, "round_start", round=round_index, planned_rounds=planned_rounds,
                          input_extraction_prompt_id=state.active_extraction_prompt.id,
                          input_analysis_prompt_id=state.active_analysis_prompt.id)
                round_record, metrics, global_iteration_counter = self.runner.run_round(state, round_index=round_index, global_iteration_counter=global_iteration_counter)
                round_duration_ms = int((time.perf_counter() - round_start_time) * 1000)
                rounds.append(round_record)
                metrics_records.append(metrics)
                self._accumulate(summary, round_record, metrics)
                summary.completed_round_count = len(rounds)
                summary.round_ids = [record.id for record in rounds]
                summary.final_extraction_prompt_version_id = state.active_extraction_prompt.id
                summary.final_analysis_prompt_version_id = state.active_analysis_prompt.id
                self._write_trend_and_summary(summary, metrics_records)
                self._save_checkpoint(round_index, state, metrics, fewshot_pool_path=str(self.store.root / "fewshot_candidate_pool.json"))
                log_stage(logger, "round_done", round=round_index, duration_ms=round_duration_ms,
                          accepted_patch_count=len(round_record.accepted_patch_ids) if round_record.accepted_patch_ids else 0,
                          rejected_patch_count=len(round_record.rejected_patch_ids) if round_record.rejected_patch_ids else 0,
                          batch_accuracy=metrics.batch_accuracy)

            summary.status = "COMPLETED"
            summary.stopped_reason = "PLANNED_ROUNDS_COMPLETED"
            self._write_trend_and_summary(summary, metrics_records)
            log_stage(logger, "optimizer_done", status="COMPLETED", completed_rounds=len(rounds),
                      final_batch_accuracy=summary.final_batch_accuracy,
                      total_accepted_patches=summary.total_accepted_patches,
                      total_rejected_patches=summary.total_rejected_patches)
            return rounds, metrics_records, summary
        except Exception as exc:
            summary.status = "FAILED"
            summary.stopped_reason = f"ERROR: {type(exc).__name__}: {exc}"
            self._write_trend_and_summary(summary, metrics_records)
            logger.exception(f"[stage=optimizer_failed] error={type(exc).__name__}: {exc}")
            raise

    def _save_checkpoint(self, round_index: int, state: OptimizerState, metrics: RoundMetrics, *, fewshot_pool_path: str | None) -> None:
        checkpoint = OptimizerCheckpoint(
            round_index=round_index,
            active_prompts={
                "extraction": asdict(state.active_extraction_prompt),
                "analysis": asdict(state.active_analysis_prompt),
            },
            sample_states = [
            {
                "sample_id": sample_state.sample_id,
                "difficulty_ema": sample_state.difficulty_ema,
                "fragility_score": sample_state.fragility_score,
                "last_selected_round": sample_state.last_selected_round,
                "consecutive_correct_count": sample_state.consecutive_correct_count,
                "consecutive_wrong_count": sample_state.consecutive_wrong_count,
                "selected_count_recent_window": sample_state.selected_count_recent_window,
                "historical_fixed": sample_state.historical_fixed,
                "toxic_trigger": sample_state.toxic_trigger,
            }
            for sample_state in state.sample_states.values()
        ],
            fewshot_pool_path=fewshot_pool_path,
            metrics_summary={
                "round_index": round_index,
                "batch_accuracy": metrics.batch_accuracy,
                "accepted_count": metrics.accepted_count,
                "rejected_count": metrics.rejected_count,
            },
        )
        checkpoint.save(self.store.root / "checkpoint.json")

    def _load_existing_checkpoint(self) -> OptimizerCheckpoint | None:
        checkpoint_path = self.store.root / "checkpoint.json"
        if not Path(checkpoint_path).exists():
            return None
        return OptimizerCheckpoint.load(checkpoint_path)

    def _restore_state_from_checkpoint(self, state: OptimizerState, checkpoint: OptimizerCheckpoint) -> None:
        """Restore active prompts and sample states from a checkpoint."""
        extraction_data = checkpoint.active_prompts.get("extraction")
        if isinstance(extraction_data, dict) and "prompt_ir" in extraction_data:
            state.active_extraction_prompt = PromptVersion.from_dict(extraction_data)
        analysis_data = checkpoint.active_prompts.get("analysis")
        if isinstance(analysis_data, dict) and "prompt_ir" in analysis_data:
            state.active_analysis_prompt = PromptVersion.from_dict(analysis_data)
        for sample_state_data in checkpoint.sample_states:
            sample_id = sample_state_data.get("sample_id")
            if sample_id is None:
                continue
            existing = state.sample_states.get(sample_id)
            if existing is None:
                continue
            existing.difficulty_ema = sample_state_data.get("difficulty_ema", existing.difficulty_ema)
            existing.fragility_score = sample_state_data.get("fragility_score", existing.fragility_score)
            existing.last_selected_round = sample_state_data.get("last_selected_round", existing.last_selected_round)
            existing.consecutive_correct_count = sample_state_data.get("consecutive_correct_count", existing.consecutive_correct_count)
            existing.consecutive_wrong_count = sample_state_data.get("consecutive_wrong_count", existing.consecutive_wrong_count)
            existing.selected_count_recent_window = sample_state_data.get("selected_count_recent_window", existing.selected_count_recent_window)
            existing.historical_fixed = sample_state_data.get("historical_fixed", existing.historical_fixed)
            existing.toxic_trigger = sample_state_data.get("toxic_trigger", existing.toxic_trigger)

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

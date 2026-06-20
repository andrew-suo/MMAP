from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class RoundStage(str, Enum):
    INIT = "init"
    OPTIMIZATION_BATCH_SELECT = "optimization_batch_select"
    BASELINE_EVAL = "baseline_eval"
    DYNAMIC_VALIDATION = "dynamic_validation"
    PATCH_GENERATION = "patch_generation"
    PATCH_VALIDATION = "patch_validation"
    PATCH_MERGED_TEST = "patch_merged_test"
    PATCH_COMPARISON = "patch_comparison"
    PATCH_TREE_REDUCE = "patch_tree_reduce"
    PATCH_EVAL = "patch_eval"
    PATCH_RANKING = "patch_ranking"
    FINAL_MERGE = "final_merge"
    PATCH_APPLY = "patch_apply"
    ANALYSIS_PROMPT_OPTIMIZATION = "analysis_prompt_optimization"
    BLIND_EVALUATION = "blind_evaluation"
    COMPRESSION = "compression"
    FEWSHOT = "fewshot"
    ANALYSIS_EVOLUTION = "analysis_evolution"
    METRICS = "metrics"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass
class RunRecord:
    id: str
    round_id: str | None
    run_type: str
    sample_id: str | None
    prompt_version_id: str
    rendered_prompt_hash: str
    model_id: str
    raw_output: str | None
    parsed_output: dict[str, Any] | None = None
    success: bool = True
    error_type: str | None = None


@dataclass
class OptimizationRound:
    id: str
    index: int
    status: str
    base_extraction_prompt_version_id: str
    base_analysis_prompt_version_id: str
    optimization_batch_ids: list[str] = field(default_factory=list)
    dynamic_validation_batch_id: str | None = None
    extraction_run_ids: list[str] = field(default_factory=list)
    dynamic_validation_run_ids: list[str] = field(default_factory=list)
    accepted_patch_ids: list[str] = field(default_factory=list)
    rejected_patch_ids: list[str] = field(default_factory=list)
    round_metrics_id: str | None = None
    analysis_evolution_report_id: str | None = None
    compression_report_ids: list[str] = field(default_factory=list)
    fewshot_report_ids: list[str] = field(default_factory=list)
    failure_reason: str | None = None
    current_stage: str = RoundStage.INIT.value


@dataclass
class BlindEvaluationRecord:
    """Blind evaluation analysis record for a single sample.

    Captures the analysis prompt's judgement without access to ground truth,
    then compares with ground truth (or 3-vote majority as fallback proxy).
    Used to filter which samples are eligible for patch generation and to
    drive the analysis prompt optimization loop.
    """

    id: str
    round_id: str
    sample_id: str
    extraction_run_id: str
    analysis_prompt_version_id: str
    blind_judgement: str
    ground_truth_label: str | None = None
    voted_truth_label: str | None = None
    three_analysis_outputs: list | None = None
    matches_truth: bool = False
    overall_status: str = "unknown"
    parse_success: bool = True
    schema_valid: bool = True
    raw_output: str | None = None
    parsed_output: dict | None = None
    extra: dict = field(default_factory=dict)


@dataclass
class BlindEvaluationReflectionRecord:
    """Reflection record for analysis prompt optimization.

    When a sample is correct in extraction but the blind evaluation
    misjudged it (analysis prompt made the wrong call), we invoke a
    reflection prompt asking what went wrong and how to improve. These
    reflections become training signal for the analysis prompt
    optimization loop.
    """

    id: str
    round_id: str
    sample_id: str
    analysis_prompt_version_id: str
    original_blind_judgement: str
    ground_truth_label: str
    why_blind_was_wrong: str = ""
    what_should_have_been_checked: str = ""
    how_to_improve_analysis: str = ""
    raw_reflection_output: str = ""
    parsed_reflection: dict | None = None
    used_voted_truth: bool = False


@dataclass
class AttemptRecord:
    """Record of a single iteration attempt for metrics tracking."""

    attempt_number: int
    round_index: int
    source: str
    extraction_base_accuracy: float | None = None
    analysis_base_accuracy: float | None = None
    reason: str = ""
    timestamp: str = ""


@dataclass
class IterationMetrics:
    """Metrics for a single iteration within a round.

    One IterationMetrics object captures a complete "extraction prompt
    optimization + analysis prompt optimization" pair. Only the
    extraction part is counted toward max_text_rounds; analysis runs
    as a shadow/follower optimization.
    """

    iteration_index: int
    round_index: int
    local_iteration_index: int

    extraction_base_accuracy: float
    extraction_base_correct_count: int
    extraction_base_total_count: int
    extraction_patched_accuracy: float | None = None
    extraction_patched_correct_count: int | None = None
    extraction_patched_total_count: int | None = None
    extraction_accepted: bool = False
    extraction_patch_count: int = 0

    analysis_base_accuracy: float | None = None
    analysis_base_correct_count: int | None = None
    analysis_base_total_count: int | None = None
    analysis_patched_accuracy: float | None = None
    analysis_patched_correct_count: int | None = None
    analysis_patched_total_count: int | None = None
    analysis_accepted: bool = False
    analysis_patch_count: int = 0

    timestamp: str = ""
    duration_seconds: float = 0.0


@dataclass
class RoundMetricsTracker:
    """Tracks all iteration metrics and failed attempts for a single round.

    The tracker is created once per round and collects metrics across all
    iterations. It also stores failed attempts for diagnostic purposes.
    """

    round_index: int
    iteration_metrics: list[IterationMetrics] = field(default_factory=list)
    failed_attempts: list[AttemptRecord] = field(default_factory=list)
    global_iteration_counter: int = 0

    def record_iteration(self, metrics: IterationMetrics) -> None:
        self.global_iteration_counter += 1
        metrics.iteration_index = self.global_iteration_counter
        metrics.local_iteration_index = len(self.iteration_metrics) + 1
        self.iteration_metrics.append(metrics)

    def record_failed_attempt(self, attempt: AttemptRecord) -> None:
        self.failed_attempts.append(attempt)

    @property
    def accepted_iteration_count(self) -> int:
        return sum(1 for m in self.iteration_metrics if m.extraction_accepted)

    def get_final_metrics(self) -> list[IterationMetrics]:
        return self.iteration_metrics

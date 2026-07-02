"""Few-shot Optimization Phase。

根据设计文档，Few-shot Optimization Phase 负责优化 few-shot 图文示例。
该 phase 在 Prompt Optimization Phase 之后执行，进入该 phase 后，文本 prompt 被锁定。

每次迭代包含两个 stage：
1. Sampling Stage
2. Few-shot Optimization Stage
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from ..core.artifacts import to_artifact_data, write_json_artifact, write_jsonl_artifact
from ..core.logging import get_logger, log_stage
from ..core.progress import NullProgressReporter, ProgressReporter
from ..stages.extraction_prompt_optimization import EvalRecord, ExtractionResult
from ..data.sampler import SamplerConfig, create_sampler
from ..data.sample import SampleBatch, SampleSet, SampleTrace, SampleSpec, SampleState
from ..prompt.structured_prompt import StructuredPrompt


@dataclass
class FewshotExample:
    """Few-shot 示例。

    ``input_images`` 表示同一个 sample 的图片集合。单图样本长度通常为 1，
    多图样本则按原始顺序记录全部图片。
    """
    id: str
    sample_id: str
    input_text: str
    output_text: str
    input_images: list[str] = field(default_factory=list)
    output_data: dict[str, Any] = field(default_factory=dict)
    rationale_text: str = ""
    rationale_source: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """转换为字典格式。"""
        return {
            "id": self.id,
            "sample_id": self.sample_id,
            "input_text": self.input_text,
            "input_images": list(self.input_images),
            "output_text": self.output_text,
            "output_data": dict(self.output_data),
            "rationale_text": self.rationale_text,
            "rationale_source": self.rationale_source,
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "FewshotExample":
        return cls(
            id=data.get("id", ""),
            sample_id=data.get("sample_id", ""),
            input_text=data.get("input_text", ""),
            input_images=list(data.get("input_images", [])),
            output_text=data.get("output_text", ""),
            output_data=dict(data.get("output_data", {})),
            rationale_text=data.get("rationale_text", ""),
            rationale_source=data.get("rationale_source", ""),
            metadata=dict(data.get("metadata", {})),
        )


@dataclass
class FewshotConfig:
    """Few-shot Optimization 配置。"""
    enabled: bool = True
    rounds: int = 2
    batch_size: int = 99
    slot_count: int = 5
    selection_batch_size: int | None = None
    validation_batch_size: int | None = None
    candidate_pool_size: int = 20
    selection_strategy: str = "quota_diverse"
    fallback_strategy: str = "difficulty_topk"
    require_no_regression: bool = True
    min_accuracy_delta: float = 0.01
    require_schema_stable: bool = True
    enable_rationale: bool = True
    rationale_max_chars: int = 200
    rationale_source_preference: list[str] = field(default_factory=lambda: [
        "prompt_optimization_history",
        "fewshot_inline_generation",
    ])
    rationale_for_candidate_types: list[str] = field(default_factory=lambda: [
        "boundary",
        "historical_misclassified",
        "high_frequency_error",
    ])
    multimodal_render_mode: str = "multi_turn"
    max_example_images: int | None = None
    max_total_images: int | None = None
    max_context_examples: int | None = None
    sampler: SamplerConfig = field(default_factory=lambda: SamplerConfig(type="frequency"))


@dataclass
class FewshotMetrics:
    """Few-shot Optimization 指标。"""
    base_accuracy: float | None = None
    final_accuracy: float | None = None
    base_correct_count: int = 0
    base_wrong_count: int = 0
    base_invalid_count: int = 0
    final_correct_count: int = 0
    final_wrong_count: int = 0
    final_invalid_count: int = 0
    accepted: bool = False
    selected_example_count: int = 0
    fixed_sample_count: int = 0
    broken_sample_count: int = 0
    schema_violation_count: int = 0
    decision_reason: str = "not_evaluated"
    fallback_used: bool = False

    def to_dict(self) -> dict[str, Any]:
        """转换为字典格式。"""
        return {
            "base_accuracy": self.base_accuracy,
            "final_accuracy": self.final_accuracy,
            "base_correct_count": self.base_correct_count,
            "base_wrong_count": self.base_wrong_count,
            "base_invalid_count": self.base_invalid_count,
            "final_correct_count": self.final_correct_count,
            "final_wrong_count": self.final_wrong_count,
            "final_invalid_count": self.final_invalid_count,
            "accepted": self.accepted,
            "selected_example_count": self.selected_example_count,
            "fixed_sample_count": self.fixed_sample_count,
            "broken_sample_count": self.broken_sample_count,
            "schema_violation_count": self.schema_violation_count,
            "decision_reason": self.decision_reason,
            "fallback_used": self.fallback_used,
        }


@dataclass
class FewshotOptimizationIterationResult:
    """Few-shot Optimization 单轮迭代结果。"""
    iteration: int
    batch: SampleBatch
    selection_batch: SampleBatch
    validation_batch: SampleBatch
    metrics: FewshotMetrics
    old_fewshot_examples: list[FewshotExample]
    new_fewshot_examples: list[FewshotExample]
    candidate_pool: list[dict[str, Any]] = field(default_factory=list)
    candidate_scores: list[dict[str, Any]] = field(default_factory=list)
    rationale_records: list[dict[str, Any]] = field(default_factory=list)
    rationale_trajectory: list[dict[str, Any]] = field(default_factory=list)
    base_results: list[ExtractionResult] = field(default_factory=list)
    base_eval_records: list[EvalRecord] = field(default_factory=list)
    final_results: list[ExtractionResult] = field(default_factory=list)
    final_eval_records: list[EvalRecord] = field(default_factory=list)
    validation_report: dict[str, Any] = field(default_factory=dict)
    decision: dict[str, Any] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """转换为字典格式。"""
        return {
            "iteration": self.iteration,
            "batch_id": self.batch.id,
            "selection_batch": self.selection_batch.to_dict(),
            "validation_batch": self.validation_batch.to_dict(),
            "metrics": self.metrics.to_dict(),
            "old_fewshot_examples": [e.to_dict() for e in self.old_fewshot_examples],
            "new_fewshot_examples": [e.to_dict() for e in self.new_fewshot_examples],
            "candidate_pool": list(self.candidate_pool),
            "candidate_scores": list(self.candidate_scores),
            "rationale_records": list(self.rationale_records),
            "rationale_trajectory": list(self.rationale_trajectory),
            "base_results": [result.to_dict() for result in self.base_results],
            "base_eval_records": [record.to_dict() for record in self.base_eval_records],
            "final_results": [result.to_dict() for result in self.final_results],
            "final_eval_records": [record.to_dict() for record in self.final_eval_records],
            "validation_report": dict(self.validation_report),
            "decision": dict(self.decision),
            "notes": list(self.notes),
        }


@dataclass
class FewshotCandidateRecord:
    sample_id: str
    candidate_type: str
    label: str
    difficulty_score: float
    last_extraction_status: str
    historical_fixed_count: int
    historical_broken_count: int
    has_images: bool
    error_pattern: str
    selection_score: float
    selection_reason: str
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "sample_id": self.sample_id,
            "candidate_type": self.candidate_type,
            "label": self.label,
            "difficulty_score": self.difficulty_score,
            "last_extraction_status": self.last_extraction_status,
            "historical_fixed_count": self.historical_fixed_count,
            "historical_broken_count": self.historical_broken_count,
            "has_images": self.has_images,
            "error_pattern": self.error_pattern,
            "selection_score": self.selection_score,
            "selection_reason": self.selection_reason,
            "metadata": dict(self.metadata),
        }


@dataclass
class FewshotRationaleRecord:
    sample_id: str
    example_id: str
    candidate_type: str
    rationale_text: str
    rationale_source: str
    rationale_mode: str
    history_inputs_used: list[str] = field(default_factory=list)
    generation_notes: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "sample_id": self.sample_id,
            "example_id": self.example_id,
            "candidate_type": self.candidate_type,
            "rationale_text": self.rationale_text,
            "rationale_source": self.rationale_source,
            "rationale_mode": self.rationale_mode,
            "history_inputs_used": list(self.history_inputs_used),
            "generation_notes": list(self.generation_notes),
            "metadata": dict(self.metadata),
        }


class FewshotOptimizationPhase:
    """Few-shot Optimization Phase。"""

    def __init__(
        self,
        config: FewshotConfig,
        extraction_prompt: StructuredPrompt,
        sample_set: SampleSet,
        output_dir: Path,
        seed: int = 42,
        initial_fewshot_examples: list[FewshotExample] | None = None,
        fewshot_executor=None,  # FewshotExecutor 实例
        checkpoint_callback: Callable[[int, "FewshotOptimizationPhase"], None] | None = None,
        progress_reporter: ProgressReporter | None = None,
    ):
        self.config = config
        self.extraction_prompt = extraction_prompt
        self.sample_set = sample_set
        self.output_dir = output_dir
        self.seed = seed
        self.fewshot_executor = fewshot_executor
        self.checkpoint_callback = checkpoint_callback
        self.progress = progress_reporter or NullProgressReporter()
        self.logger = get_logger(__name__)
        if self.fewshot_executor is not None and hasattr(self.fewshot_executor, "progress_reporter"):
            self.fewshot_executor.progress_reporter = self.progress

        # 创建 sampler
        self.sampler = create_sampler(config.sampler)

        # 初始化 few-shot examples
        self.fewshot_examples = initial_fewshot_examples or []

        # 结果存储
        self.iteration_results: list[FewshotOptimizationIterationResult] = []

    def run(self, start_iteration: int = 1) -> list[FewshotOptimizationIterationResult]:
        """执行完整的 Few-shot Optimization Phase。"""
        if not self.config.enabled:
            return []

        self.progress.stage("\n--- Phase 3: Few-shot 优化 ---")
        max_iterations = self.config.rounds

        for iteration in range(start_iteration, max_iterations + 1):
            self.progress.stage(f"  迭代 {iteration}/{max_iterations}")
            log_stage(self.logger, "fewshot_iteration_start", iteration=iteration, rounds=max_iterations)
            result = self._run_iteration(iteration)
            self.iteration_results.append(result)
            if result.metrics.final_accuracy is not None:
                self.progress.stage(f"  迭代 {iteration} 完成，准确率: {result.metrics.final_accuracy:.2%}")
            else:
                self.progress.stage(f"  迭代 {iteration} 完成")
            log_stage(
                self.logger,
                "fewshot_iteration_done",
                iteration=iteration,
                final_accuracy=result.metrics.final_accuracy,
                accepted=result.metrics.accepted,
                selected_examples=result.metrics.selected_example_count,
            )
            if self.checkpoint_callback is not None:
                self.checkpoint_callback(iteration, self)

        # 输出最终准确率
        if self.iteration_results:
            last_acc = self.iteration_results[-1].metrics.final_accuracy
            if last_acc is not None:
                self.progress.stage(f"Few-shot 优化完成，准确率: {last_acc:.2%}")
            else:
                self.progress.stage("Few-shot 优化完成")

        return self.iteration_results

    def _run_iteration(self, iteration: int) -> FewshotOptimizationIterationResult:
        """执行单轮迭代。"""
        # Stage 1: Sampling Stage
        batch = self._sampling_stage(iteration)
        selection_batch, validation_batch, split_notes = self._split_batches(batch)

        # Stage 2: Few-shot Optimization Stage
        (
            metrics,
            new_examples,
            candidate_pool,
            candidate_scores,
            rationale_records,
            rationale_trajectory,
            base_results,
            base_eval_records,
            final_results,
            final_eval_records,
            validation_report,
            decision,
            stage_notes,
        ) = self._fewshot_optimization_stage(iteration, batch)

        # 构造结果
        result = FewshotOptimizationIterationResult(
            iteration=iteration,
            batch=batch,
            selection_batch=selection_batch,
            validation_batch=validation_batch,
            metrics=metrics,
            old_fewshot_examples=self.fewshot_examples.copy(),
            new_fewshot_examples=new_examples,
            candidate_pool=candidate_pool,
            candidate_scores=candidate_scores,
            rationale_records=rationale_records,
            rationale_trajectory=rationale_trajectory,
            base_results=base_results,
            base_eval_records=base_eval_records,
            final_results=final_results,
            final_eval_records=final_eval_records,
            validation_report=validation_report,
            decision=decision,
            notes=split_notes + stage_notes,
        )

        # 更新 few-shot examples（如果接受）
        if metrics.accepted:
            self.fewshot_examples = new_examples

        # 保存 artifact
        self._save_iteration_artifacts(iteration, result)

        return result

    def _sampling_stage(self, iteration: int) -> SampleBatch:
        """Sampling Stage。"""
        batch = self.sampler.sample(
            sample_set=self.sample_set,
            batch_size=self.config.batch_size,
            iteration=iteration,
            seed=self.seed,
        )

        # 设置 phase
        batch.phase = "fewshot_optimization"

        # 清除该轮次的旧 traces
        self.sample_set.clear_traces_for_iteration("fewshot_optimization", iteration)

        # 为每个被选中的样本创建 trace
        for sample_id in batch.sample_ids:
            trace = SampleTrace(
                sample_id=sample_id,
                phase="fewshot_optimization",
                iteration=iteration,
                selected=True,
            )
            self.sample_set.add_trace(trace)

        return batch

    def _split_batches(self, batch: SampleBatch) -> tuple[SampleBatch, SampleBatch, list[str]]:
        sample_ids = list(batch.sample_ids)
        notes: list[str] = []
        if not sample_ids:
            empty_selection = self._clone_batch(batch, "selection", [])
            empty_validation = self._clone_batch(batch, "validation", [])
            notes.append("empty_batch")
            return empty_selection, empty_validation, notes

        selection_target = self.config.selection_batch_size
        validation_target = self.config.validation_batch_size
        total = len(sample_ids)

        if selection_target is None:
            selection_target = min(total, max(self.config.slot_count, total // 2 or 1))
            if total > 1:
                selection_target = min(selection_target, total - 1)
        selection_ids = sample_ids[:max(0, min(total, selection_target))]

        remaining_ids = sample_ids[len(selection_ids):]
        if validation_target is None:
            validation_target = len(remaining_ids)
            if validation_target <= 0:
                validation_target = total
        validation_ids = remaining_ids[:max(0, min(len(remaining_ids), validation_target))]

        if not selection_ids:
            selection_ids = sample_ids[: min(total, self.config.slot_count)]
            notes.append("selection_batch_auto_filled")
        if not validation_ids:
            validation_ids = sample_ids[: max(1, min(total, validation_target))]
            notes.append("validation_overlap_fallback")

        if set(selection_ids) & set(validation_ids):
            notes.append("selection_validation_overlap")

        return (
            self._clone_batch(batch, "selection", selection_ids),
            self._clone_batch(batch, "validation", validation_ids),
            notes,
        )

    @staticmethod
    def _clone_batch(batch: SampleBatch, suffix: str, sample_ids: list[str]) -> SampleBatch:
        return SampleBatch(
            id=f"{batch.id}_{suffix}",
            phase=batch.phase,
            iteration=batch.iteration,
            sample_ids=list(sample_ids),
            sampler_name=batch.sampler_name,
            scores=dict(batch.scores),
            metadata={**dict(batch.metadata), "subset": suffix},
            warnings=list(batch.warnings),
        )

    def _fewshot_optimization_stage(
        self,
        iteration: int,
        batch: SampleBatch,
    ) -> tuple[
        FewshotMetrics,
        list[FewshotExample],
        list[dict[str, Any]],
        list[dict[str, Any]],
        list[dict[str, Any]],
        list[dict[str, Any]],
        list[ExtractionResult],
        list[EvalRecord],
        list[ExtractionResult],
        list[EvalRecord],
        dict[str, Any],
        dict[str, Any],
        list[str],
    ]:
        """Few-shot Optimization Stage。"""
        metrics = FewshotMetrics()
        notes: list[str] = []
        selection_batch, validation_batch, split_notes = self._split_batches(batch)
        notes.extend(split_notes)

        candidate_records, fallback_used, selection_notes = self._build_candidate_pool(selection_batch)
        notes.extend(selection_notes)
        new_examples, rationale_records = self._select_candidate_examples(
            candidate_records,
            force_fallback=fallback_used,
        )
        new_examples, budget_notes = self._apply_example_budget(new_examples)
        notes.extend(budget_notes)
        metrics.selected_example_count = len(new_examples)
        metrics.fallback_used = fallback_used
        rationale_records = self._sync_rationale_records_with_examples(rationale_records, new_examples)
        rationale_trajectory = [self._rationale_trajectory_payload(record) for record in rationale_records]

        base_extraction_results = self._execute_extraction(validation_batch)
        base_eval_records = self._compute_base_metrics(validation_batch, base_extraction_results, metrics)
        final_extraction_results: list[ExtractionResult] = []
        final_eval_records: list[EvalRecord] = []
        validation_report: dict[str, Any] = self._build_validation_report(
            validation_batch=validation_batch,
            candidate_records=candidate_records,
            base_eval_records=base_eval_records,
            final_eval_records=[],
        )
        decision: dict[str, Any] = self._build_decision(metrics, validation_report, accepted=False)

        if new_examples:
            final_extraction_results = self._execute_extraction_with_fewshot(validation_batch, new_examples)
            final_eval_records = self._compute_final_metrics(validation_batch, final_extraction_results, metrics)
            validation_report = self._build_validation_report(
                validation_batch=validation_batch,
                candidate_records=candidate_records,
                base_eval_records=base_eval_records,
                final_eval_records=final_eval_records,
            )
            metrics.accepted, metrics.decision_reason = self._decide_acceptance(metrics, validation_report)
            decision = self._build_decision(metrics, validation_report, accepted=metrics.accepted)
        else:
            metrics.accepted = False
            metrics.decision_reason = "insufficient_candidates"
            decision = self._build_decision(metrics, validation_report, accepted=False)

        return (
            metrics,
            new_examples,
            [item.to_dict() for item in candidate_records],
            [self._candidate_score_payload(item) for item in candidate_records],
            [item.to_dict() for item in rationale_records],
            rationale_trajectory,
            base_extraction_results,
            base_eval_records,
            final_extraction_results,
            final_eval_records,
            validation_report,
            decision,
            notes,
        )

    def _execute_extraction(self, batch: SampleBatch) -> list[ExtractionResult]:
        """执行抽取（使用当前 few-shot examples）。"""
        if self.fewshot_executor is not None:
            results = self.fewshot_executor.execute_extraction(
                extraction_prompt=self.extraction_prompt,
                fewshot_examples=self.fewshot_examples,
                batch=batch,
                sample_set=self.sample_set,
            )
            # 更新 SampleTrace
            for result in results:
                traces = self.sample_set.get_traces_for_iteration("fewshot_optimization", batch.iteration)
                for trace in traces:
                    if trace.sample_id == result.sample_id:
                        trace.base_extraction_result_id = result.sample_id
            return results

        results: list[ExtractionResult] = []

        for sample_id in batch.sample_ids:
            spec = self.sample_set.specs.get(sample_id)
            if spec is None:
                continue

            # Mock 抽取结果
            result = ExtractionResult(
                sample_id=sample_id,
                raw_output="mock fewshot output",
                parsed_output={"mock": "fewshot_data"},
                status="correct",
            )
            results.append(result)

            # 更新 SampleTrace
            traces = self.sample_set.get_traces_for_iteration("fewshot_optimization", batch.iteration)
            for trace in traces:
                if trace.sample_id == sample_id:
                    trace.base_extraction_result_id = result.sample_id

        return results

    def _execute_extraction_with_fewshot(
        self,
        batch: SampleBatch,
        fewshot_examples: list[FewshotExample],
    ) -> list[ExtractionResult]:
        """使用新的 few-shot examples 执行抽取。"""
        if self.fewshot_executor is not None:
            results = self.fewshot_executor.execute_validation(
                extraction_prompt=self.extraction_prompt,
                fewshot_examples=fewshot_examples,
                batch=batch,
                sample_set=self.sample_set,
            )
            # 更新 SampleTrace
            for result in results:
                traces = self.sample_set.get_traces_for_iteration("fewshot_optimization", batch.iteration)
                for trace in traces:
                    if trace.sample_id == result.sample_id:
                        trace.final_extraction_result_id = result.sample_id
            return results

        results: list[ExtractionResult] = []

        for sample_id in batch.sample_ids:
            spec = self.sample_set.specs.get(sample_id)
            if spec is None:
                continue

            # Mock 抽取结果
            result = ExtractionResult(
                sample_id=sample_id,
                raw_output="mock fewshot final output",
                parsed_output={"mock": "fewshot_final_data"},
                status="correct",
            )
            results.append(result)

            # 更新 SampleTrace
            traces = self.sample_set.get_traces_for_iteration("fewshot_optimization", batch.iteration)
            for trace in traces:
                if trace.sample_id == sample_id:
                    trace.final_extraction_result_id = result.sample_id

        return results

    def _compute_base_metrics(
        self,
        batch: SampleBatch,
        results: list[ExtractionResult],
        metrics: FewshotMetrics,
    ) -> list[EvalRecord]:
        """统计原始 few-shot 指标。"""
        if self.fewshot_executor is not None:
            eval_records = self.fewshot_executor.evaluate_results(results, self.sample_set)
            accuracy = self.fewshot_executor.compute_accuracy(eval_records)
            correct_count = sum(1 for r in eval_records if r.correct)
            wrong_count = sum(1 for r in eval_records if r.status == "wrong")
            invalid_count = sum(1 for r in eval_records if r.status == "invalid")
            total = len(eval_records)

            metrics.base_correct_count = correct_count
            metrics.base_wrong_count = wrong_count
            metrics.base_invalid_count = invalid_count
            metrics.base_accuracy = accuracy if total > 0 else 0.0

            self._apply_eval_records_to_base_traces(batch, eval_records)
            return eval_records

        correct_count = sum(1 for r in results if r.status == "correct")
        wrong_count = sum(1 for r in results if r.status == "wrong")
        invalid_count = sum(1 for r in results if r.status == "invalid")
        total = len(results)

        metrics.base_correct_count = correct_count
        metrics.base_wrong_count = wrong_count
        metrics.base_invalid_count = invalid_count
        metrics.base_accuracy = correct_count / total if total > 0 else 0.0

        # 更新样本状态
        for result in results:
            state = self.sample_set.states.get(result.sample_id)
            if state:
                has_error = result.status in ["wrong", "invalid"]
                state.update_error(has_error)
                state.last_extraction_status = result.status

        eval_records = self._build_eval_records_from_results(results)
        self._apply_eval_records_to_base_traces(batch, eval_records)
        return eval_records

    def _compute_final_metrics(
        self,
        batch: SampleBatch,
        results: list[ExtractionResult],
        metrics: FewshotMetrics,
    ) -> list[EvalRecord]:
        """统计最终 few-shot 指标。"""
        if self.fewshot_executor is not None:
            eval_sample_set = copy.deepcopy(self.sample_set)
            eval_records = self.fewshot_executor.evaluate_results(results, eval_sample_set)
            accuracy = self.fewshot_executor.compute_accuracy(eval_records)
            correct_count = sum(1 for r in eval_records if r.correct)
            wrong_count = sum(1 for r in eval_records if r.status == "wrong")
            invalid_count = sum(1 for r in eval_records if r.status == "invalid")
            total = len(eval_records)

            metrics.final_correct_count = correct_count
            metrics.final_wrong_count = wrong_count
            metrics.final_invalid_count = invalid_count
            metrics.final_accuracy = accuracy if total > 0 else 0.0
            self._apply_eval_records_to_final_traces(batch, eval_records)
            return eval_records

        correct_count = sum(1 for r in results if r.status == "correct")
        wrong_count = sum(1 for r in results if r.status == "wrong")
        invalid_count = sum(1 for r in results if r.status == "invalid")
        total = len(results)

        metrics.final_correct_count = correct_count
        metrics.final_wrong_count = wrong_count
        metrics.final_invalid_count = invalid_count
        metrics.final_accuracy = correct_count / total if total > 0 else 0.0
        eval_records = self._build_eval_records_from_results(results)
        self._apply_eval_records_to_final_traces(batch, eval_records)
        return eval_records

    def _build_eval_records_from_results(
        self,
        results: list[ExtractionResult],
    ) -> list[EvalRecord]:
        """为 mock 路径构造与执行结果一致的评测记录。"""
        eval_records: list[EvalRecord] = []
        for result in results:
            status = result.evaluation_status or result.status
            eval_records.append(
                EvalRecord(
                    sample_id=result.sample_id,
                    extraction_result_id=result.sample_id,
                    status=status,
                    correct=(status == "correct"),
                    details={},
                )
            )
        return eval_records

    def _apply_eval_records_to_base_traces(
        self,
        batch: SampleBatch,
        eval_records: list[EvalRecord],
    ) -> None:
        """把 base 评测结果回填到样本状态与 trace。"""
        self._apply_eval_records_to_traces(batch, eval_records, "base_extraction_status")

    def _apply_eval_records_to_final_traces(
        self,
        batch: SampleBatch,
        eval_records: list[EvalRecord],
    ) -> None:
        """把 final 评测结果回填到样本状态与 trace。"""
        self._apply_eval_records_to_traces(batch, eval_records, "final_extraction_status")

    def _apply_eval_records_to_traces(
        self,
        batch: SampleBatch,
        eval_records: list[EvalRecord],
        trace_status_attr: str,
    ) -> None:
        """按 sample_id 用 EvalRecord.status 回填 trace 状态。"""
        if not eval_records:
            return

        status_by_sample_id = {record.sample_id: record.status for record in eval_records}
        traces = self.sample_set.get_traces_for_iteration("fewshot_optimization", batch.iteration)
        trace_by_sample_id = {trace.sample_id: trace for trace in traces}

        for sample_id, status in status_by_sample_id.items():
            trace = trace_by_sample_id.get(sample_id)
            if trace is not None:
                setattr(trace, trace_status_attr, status)

    def _build_candidate_pool(
        self,
        batch: SampleBatch,
    ) -> tuple[list[FewshotCandidateRecord], bool, list[str]]:
        records: list[FewshotCandidateRecord] = []
        notes: list[str] = []

        for sample_id in batch.sample_ids:
            spec = self.sample_set.specs.get(sample_id)
            state = self.sample_set.states.get(sample_id)
            if spec is None or state is None or not spec.ground_truth:
                continue
            candidate_type, reason, error_pattern = self._classify_candidate(spec, state)
            score = self._candidate_score(state, candidate_type)
            records.append(
                FewshotCandidateRecord(
                    sample_id=sample_id,
                    candidate_type=candidate_type,
                    label=self._ground_truth_label(spec.ground_truth),
                    difficulty_score=float(state.difficulty_score),
                    last_extraction_status=state.last_extraction_status,
                    historical_fixed_count=state.historical_fixed_count,
                    historical_broken_count=state.historical_broken_count,
                    has_images=any(asset.type == "image" for asset in spec.assets),
                    error_pattern=error_pattern,
                    selection_score=score,
                    selection_reason=reason,
                    metadata={
                        "selected_from": batch.id,
                        "assets_count": len(spec.assets),
                    },
                )
            )

        records.sort(key=lambda item: item.selection_score, reverse=True)
        pool_limit = max(self.config.slot_count, self.config.candidate_pool_size)
        trimmed = records[:pool_limit]

        fallback_used = self.config.selection_strategy != "quota_diverse"
        if self.config.selection_strategy == "quota_diverse":
            distinct_types = {item.candidate_type for item in trimmed}
            if len(distinct_types) < min(self.config.slot_count, 3):
                fallback_used = True
                notes.append("candidate_pool_diversity_insufficient")
        else:
            notes.append(f"selection_strategy={self.config.selection_strategy}")
        return trimmed, fallback_used, notes

    def _classify_candidate(
        self,
        spec: SampleSpec,
        state: SampleState,
    ) -> tuple[str, str, str]:
        status = state.last_extraction_status
        if state.error_count >= 2:
            return "high_frequency_error", "repeated extraction failures", "repeated_error"
        if state.historical_fixed_count > 0 or state.historical_broken_count > 0:
            return "historical_misclassified", "historical prompt sensitivity", "historical_flip"
        if state.difficulty_score >= 0.6:
            return "boundary", "high difficulty boundary sample", "boundary_case"
        if status in {"wrong", "invalid"}:
            return "canonical_negative", "current extraction failure", status
        return "canonical_positive", "stable correct baseline", "stable_correct"

    @staticmethod
    def _candidate_score(state: SampleState, candidate_type: str) -> float:
        bonus_by_type = {
            "historical_misclassified": 0.35,
            "high_frequency_error": 0.30,
            "boundary": 0.20,
            "canonical_negative": 0.10,
            "canonical_positive": 0.05,
        }
        return (
            float(state.difficulty_score)
            + float(state.error_ema)
            + bonus_by_type.get(candidate_type, 0.0)
        )

    def _select_candidate_examples(
        self,
        candidate_records: list[FewshotCandidateRecord],
        *,
        force_fallback: bool = False,
    ) -> tuple[list[FewshotExample], list[FewshotRationaleRecord]]:
        if not candidate_records:
            return [], []
        if force_fallback or self.config.selection_strategy != "quota_diverse":
            return self._build_examples_from_candidates(candidate_records[: self.config.slot_count])

        selected_records: list[FewshotCandidateRecord] = []
        selected_ids: set[str] = set()
        priority = self._selection_priority(candidate_records)
        by_type: dict[str, list[FewshotCandidateRecord]] = {name: [] for name in priority}
        remainder: list[FewshotCandidateRecord] = []
        for record in candidate_records:
            if record.candidate_type in by_type:
                by_type[record.candidate_type].append(record)
            else:
                remainder.append(record)

        for candidate_type in priority:
            if len(selected_records) >= self.config.slot_count:
                break
            for record in by_type.get(candidate_type, []):
                if record.sample_id in selected_ids:
                    continue
                selected_records.append(record)
                selected_ids.add(record.sample_id)
                break

        for record in candidate_records:
            if len(selected_records) >= self.config.slot_count:
                break
            if record.sample_id in selected_ids:
                continue
            selected_records.append(record)
            selected_ids.add(record.sample_id)

        return self._build_examples_from_candidates(selected_records)

    def _selection_priority(
        self,
        candidate_records: list[FewshotCandidateRecord],
    ) -> list[str]:
        default_priority = [
            "canonical_positive",
            "canonical_negative",
            "high_frequency_error",
            "boundary",
            "historical_misclassified",
        ]
        if not self.config.enable_rationale:
            return default_priority

        prefer_history = "prompt_optimization_history" in set(self.config.rationale_source_preference)
        if not prefer_history:
            return default_priority

        has_historical_candidate = any(
            record.candidate_type == "historical_misclassified"
            for record in candidate_records
        )
        if not has_historical_candidate:
            return default_priority

        return [
            "canonical_positive",
            "canonical_negative",
            "high_frequency_error",
            "historical_misclassified",
            "boundary",
        ]

    def _build_examples_from_candidates(
        self,
        candidate_records: list[FewshotCandidateRecord],
    ) -> tuple[list[FewshotExample], list[FewshotRationaleRecord]]:
        examples: list[FewshotExample] = []
        rationale_records: list[FewshotRationaleRecord] = []
        limit = self.config.max_context_examples or self.config.slot_count
        for record in self.progress.iter(
            candidate_records[:limit],
            desc="Building few-shot examples",
            total=min(len(candidate_records), limit),
        ):
            spec = self.sample_set.specs.get(record.sample_id)
            if spec is None:
                continue
            example, rationale_record = self._build_example_from_spec(spec, record)
            examples.append(example)
            if rationale_record is not None:
                rationale_records.append(rationale_record)
        return examples, rationale_records

    def _build_example_from_spec(
        self,
        spec: SampleSpec,
        record: FewshotCandidateRecord | None = None,
    ) -> tuple[FewshotExample, FewshotRationaleRecord | None]:
        images = [
            img for img in (
                asset.uri or asset.local_path or ""
                for asset in spec.assets
                if asset.type == "image"
            )
            if img
        ]
        if self.config.max_example_images is not None:
            images = images[: max(0, self.config.max_example_images)]
        metadata: dict[str, Any] = {
            "render_mode": self.config.multimodal_render_mode,
        }
        if record is not None:
            metadata.update(
                {
                    "candidate_type": record.candidate_type,
                    "selection_reason": record.selection_reason,
                    "selection_score": record.selection_score,
                }
            )
        rationale_text = ""
        rationale_source = ""
        rationale_record: FewshotRationaleRecord | None = None
        if self.config.enable_rationale and record is not None:
            rationale_text, rationale_source, rationale_mode, history_inputs_used, generation_notes = (
                self._build_rationale_for_sample(spec, record)
            )
            metadata.update(
                {
                    "rationale_enabled": bool(rationale_text),
                    "rationale_mode": rationale_mode,
                    "rationale_source": rationale_source,
                }
            )
            if rationale_text:
                rationale_record = FewshotRationaleRecord(
                    sample_id=spec.id,
                    example_id=f"fewshot_{spec.id}",
                    candidate_type=record.candidate_type,
                    rationale_text=rationale_text,
                    rationale_source=rationale_source,
                    rationale_mode=rationale_mode,
                    history_inputs_used=history_inputs_used,
                    generation_notes=generation_notes,
                    metadata={
                        "has_images": bool(images),
                        "image_count": len(images),
                    },
                )
        example = FewshotExample(
            id=f"fewshot_{spec.id}",
            sample_id=spec.id,
            input_text=str(spec.input),
            input_images=images,
            output_text=str(spec.ground_truth),
            output_data=spec.ground_truth,
            rationale_text=rationale_text,
            rationale_source=rationale_source,
            metadata=metadata,
        )
        return example, rationale_record

    def _apply_example_budget(
        self,
        examples: list[FewshotExample],
    ) -> tuple[list[FewshotExample], list[str]]:
        if not examples:
            return [], []
        notes: list[str] = []
        limited = list(examples)
        if self.config.max_context_examples is not None:
            max_examples = max(0, self.config.max_context_examples)
            if len(limited) > max_examples:
                limited = limited[:max_examples]
                notes.append("max_context_examples_trimmed")
        if self.config.max_total_images is not None:
            total_images = 0
            kept: list[FewshotExample] = []
            for example in limited:
                image_count = len(example.input_images)
                if total_images + image_count > self.config.max_total_images:
                    notes.append("max_total_images_trimmed")
                    break
                kept.append(example)
                total_images += image_count
            limited = kept
        return limited, notes

    def _build_rationale_for_sample(
        self,
        spec: SampleSpec,
        record: FewshotCandidateRecord,
    ) -> tuple[str, str, str, list[str], list[str]]:
        if not self._should_attach_rationale(spec, record):
            return "", "", "disabled", [], ["rationale_skipped"]
        state = self.sample_set.states.get(spec.id)
        history_text, history_inputs_used, history_notes = self._history_based_rationale(
            spec,
            record,
            state,
        )
        if history_text:
            return history_text, "prompt_optimization_history", "history_based", history_inputs_used, history_notes
        inline_text, inline_notes = self._inline_rationale(spec, record, state)
        if inline_text:
            return inline_text, "fewshot_inline_generation", "inline_generate", [], inline_notes
        return "", "", "empty", history_inputs_used, history_notes + inline_notes

    def _should_attach_rationale(
        self,
        spec: SampleSpec,
        record: FewshotCandidateRecord,
    ) -> bool:
        if len([asset for asset in spec.assets if asset.type == "image"]) > 1:
            return True
        return record.candidate_type in set(self.config.rationale_for_candidate_types)

    def _history_based_rationale(
        self,
        spec: SampleSpec,
        record: FewshotCandidateRecord,
        state: SampleState | None,
    ) -> tuple[str, list[str], list[str]]:
        if state is None:
            return "", [], ["no_state_for_history"]
        trajectories = state.get_optimization_trajectory(limit=6)
        if not trajectories:
            return "", [], ["no_optimization_trajectory"]
        history_inputs_used: list[str] = []
        notes: list[str] = []
        rationale_parts: list[str] = []
        analysis_trajectories = [t for t in trajectories if t.prompt_type == "analysis"]
        extraction_trajectories = [t for t in trajectories if t.prompt_type == "extraction"]
        latest_analysis = analysis_trajectories[-1] if analysis_trajectories else None
        latest_extraction = extraction_trajectories[-1] if extraction_trajectories else None

        if latest_analysis is not None:
            analysis_reason = latest_analysis.analysis_summary.get("error_reason")
            if analysis_reason:
                rationale_parts.append(self._normalize_rationale_text(analysis_reason))
                history_inputs_used.append("analysis_summary.error_reason")
            reflection_reason = latest_analysis.reflection_summary.get("error_reason")
            if reflection_reason and not rationale_parts:
                rationale_parts.append(self._normalize_rationale_text(reflection_reason))
                history_inputs_used.append("reflection_summary.error_reason")
        if latest_extraction is not None and not rationale_parts:
            attempts = latest_extraction.latest_patch_attempts(limit=3)
            for attempt in reversed(attempts):
                if attempt.rationale:
                    rationale_parts.append(self._normalize_rationale_text(attempt.rationale))
                    history_inputs_used.append("patch_attempts.rationale")
                    break
                if attempt.rejection_reason:
                    rationale_parts.append(self._normalize_rationale_text(attempt.rejection_reason))
                    history_inputs_used.append("patch_attempts.rejection_reason")
                    break

        rationale = " ".join(part for part in rationale_parts if part).strip()
        if not rationale:
            notes.append("history_available_but_no_reason")
        rationale = self._augment_rationale_with_sample_context(rationale, spec, record)
        rationale = self._truncate_rationale(rationale)
        return rationale, history_inputs_used, notes

    def _inline_rationale(
        self,
        spec: SampleSpec,
        record: FewshotCandidateRecord,
        state: SampleState | None,
    ) -> tuple[str, list[str]]:
        notes: list[str] = []
        parts: list[str] = []
        image_count = len([asset for asset in spec.assets if asset.type == "image"])
        if image_count > 1:
            parts.append("Consider all provided images together before deciding the sample-level label.")
        candidate_type = record.candidate_type
        if candidate_type == "boundary":
            parts.append("The label depends on a subtle boundary condition rather than a single obvious cue.")
        elif candidate_type == "historical_misclassified":
            parts.append("This is a historically unstable case, so rely on the decisive evidence and avoid repeating prior mistakes.")
        elif candidate_type == "high_frequency_error":
            parts.append("This sample represents a frequent failure pattern and should be checked against the main error cue.")
        elif candidate_type == "canonical_negative":
            parts.append("The final label is driven by a clear failure condition in the sample.")
        if state is not None and state.last_extraction_status in {"wrong", "invalid"}:
            parts.append("Do not rely on superficial similarity to previously correct examples.")
        rationale = self._truncate_rationale(" ".join(parts).strip())
        if not rationale:
            notes.append("inline_rationale_empty")
        return rationale, notes

    @staticmethod
    def _normalize_rationale_text(text: str) -> str:
        return " ".join(str(text).split())

    def _augment_rationale_with_sample_context(
        self,
        rationale: str,
        spec: SampleSpec,
        record: FewshotCandidateRecord,
    ) -> str:
        parts: list[str] = []
        if rationale:
            parts.append(rationale)
        image_count = len([asset for asset in spec.assets if asset.type == "image"])
        if image_count > 1 and "all provided images together" not in rationale.lower():
            parts.append("Consider all provided images together before deciding the sample-level label.")
        if record.candidate_type == "boundary" and "boundary" not in rationale.lower():
            parts.append("Focus on the boundary cue that separates this case from similar examples.")
        return " ".join(parts).strip()

    def _truncate_rationale(self, rationale: str) -> str:
        text = rationale.strip()
        if not text:
            return ""
        limit = max(20, self.config.rationale_max_chars)
        if len(text) <= limit:
            return text
        return text[: limit - 3].rstrip() + "..."

    @staticmethod
    def _sync_rationale_records_with_examples(
        records: list[FewshotRationaleRecord],
        examples: list[FewshotExample],
    ) -> list[FewshotRationaleRecord]:
        valid_ids = {example.id for example in examples}
        return [record for record in records if record.example_id in valid_ids]

    @staticmethod
    def _rationale_trajectory_payload(record: FewshotRationaleRecord) -> dict[str, Any]:
        return {
            "sample_id": record.sample_id,
            "example_id": record.example_id,
            "candidate_type": record.candidate_type,
            "rationale_source": record.rationale_source,
            "rationale_mode": record.rationale_mode,
            "history_inputs_used": list(record.history_inputs_used),
            "generation_notes": list(record.generation_notes),
        }

    def _build_validation_report(
        self,
        *,
        validation_batch: SampleBatch,
        candidate_records: list[FewshotCandidateRecord],
        base_eval_records: list[EvalRecord],
        final_eval_records: list[EvalRecord],
    ) -> dict[str, Any]:
        base_by_sample = {record.sample_id: record for record in base_eval_records}
        final_by_sample = {record.sample_id: record for record in final_eval_records}
        fixed_sample_ids: list[str] = []
        broken_sample_ids: list[str] = []
        schema_violation_sample_ids: list[str] = []

        for sample_id in validation_batch.sample_ids:
            base = base_by_sample.get(sample_id)
            final = final_by_sample.get(sample_id)
            if final is None:
                continue
            if base is not None and base.status != "correct" and final.status == "correct":
                fixed_sample_ids.append(sample_id)
            if base is not None and base.status == "correct" and final.status != "correct":
                broken_sample_ids.append(sample_id)
            if final.status == "invalid" and (base is None or base.status != "invalid"):
                schema_violation_sample_ids.append(sample_id)

        return {
            "selection_strategy": self.config.selection_strategy,
            "fallback_strategy": self.config.fallback_strategy,
            "validation_sample_ids": list(validation_batch.sample_ids),
            "candidate_sample_ids": [item.sample_id for item in candidate_records],
            "fixed_sample_ids": fixed_sample_ids,
            "broken_sample_ids": broken_sample_ids,
            "schema_violation_sample_ids": schema_violation_sample_ids,
            "base_eval_count": len(base_eval_records),
            "final_eval_count": len(final_eval_records),
        }

    def _decide_acceptance(
        self,
        metrics: FewshotMetrics,
        validation_report: dict[str, Any],
    ) -> tuple[bool, str]:
        if metrics.base_accuracy is None or metrics.final_accuracy is None:
            return False, "missing_accuracy"
        delta = metrics.final_accuracy - metrics.base_accuracy
        broken_count = len(validation_report.get("broken_sample_ids", []))
        schema_violation_count = len(validation_report.get("schema_violation_sample_ids", []))
        metrics.fixed_sample_count = len(validation_report.get("fixed_sample_ids", []))
        metrics.broken_sample_count = broken_count
        metrics.schema_violation_count = schema_violation_count
        if self.config.require_no_regression and broken_count > 0:
            return False, "regression_detected"
        if self.config.require_schema_stable and schema_violation_count > 0:
            return False, "schema_worsened"
        if delta < self.config.min_accuracy_delta:
            if metrics.final_correct_count > metrics.base_correct_count and broken_count == 0:
                return True, "improved_correct_count"
            return False, "no_delta"
        return True, "improved_without_regression"

    @staticmethod
    def _build_decision(
        metrics: FewshotMetrics,
        validation_report: dict[str, Any],
        *,
        accepted: bool,
    ) -> dict[str, Any]:
        return {
            "accepted": accepted,
            "decision_reason": metrics.decision_reason,
            "base_accuracy": metrics.base_accuracy,
            "final_accuracy": metrics.final_accuracy,
            "fixed_sample_ids": list(validation_report.get("fixed_sample_ids", [])),
            "broken_sample_ids": list(validation_report.get("broken_sample_ids", [])),
            "schema_violation_sample_ids": list(validation_report.get("schema_violation_sample_ids", [])),
            "fallback_used": metrics.fallback_used,
        }

    @staticmethod
    def _candidate_score_payload(record: FewshotCandidateRecord) -> dict[str, Any]:
        return {
            "sample_id": record.sample_id,
            "candidate_type": record.candidate_type,
            "selection_score": record.selection_score,
            "selection_reason": record.selection_reason,
        }

    @staticmethod
    def _ground_truth_label(ground_truth: dict[str, Any]) -> str:
        if not ground_truth:
            return ""
        values = [str(value) for value in ground_truth.values() if value is not None]
        return " | ".join(values[:3])

    def _select_difficult_samples(
        self,
        batch: SampleBatch,
        metrics: FewshotMetrics,
    ) -> list[FewshotExample]:
        """兼容旧测试入口：当前实现走 candidate pool + 选择策略。"""
        candidate_records, fallback_used, _ = self._build_candidate_pool(batch)
        examples, _ = self._select_candidate_examples(candidate_records, force_fallback=fallback_used)
        examples, _ = self._apply_example_budget(examples)
        return examples

    def _save_iteration_artifacts(
        self,
        iteration: int,
        result: FewshotOptimizationIterationResult,
    ) -> None:
        """保存单轮迭代的 artifacts。"""
        import json

        iteration_dir = self.output_dir / "fewshot_optimization" / f"iteration_{iteration}"
        iteration_dir.mkdir(parents=True, exist_ok=True)

        # 保存 batch
        write_json_artifact(iteration_dir / "sample_batch.json", result.batch.to_dict())
        write_json_artifact(iteration_dir / "selection_batch.json", result.selection_batch.to_dict())
        write_json_artifact(iteration_dir / "validation_batch.json", result.validation_batch.to_dict())

        # PR4: 保存 sample traces
        traces = self.sample_set.get_traces_for_iteration("fewshot_optimization", iteration)
        with open(iteration_dir / "sample_traces.jsonl", "w", encoding="utf-8") as f:
            for trace in traces:
                trace_dict = {
                    "sample_id": trace.sample_id,
                    "phase": trace.phase,
                    "iteration": trace.iteration,
                    "selected": trace.selected,
                }
                f.write(json.dumps(to_artifact_data(trace_dict), ensure_ascii=False) + "\n")

        # PR4: 保存 fewshot/ 子目录
        fewshot_dir = iteration_dir / "fewshot"
        fewshot_dir.mkdir(parents=True, exist_ok=True)

        def _write_jsonl(path, items):
            write_jsonl_artifact(path, items)

        def _write_json(path, data):
            write_json_artifact(path, data)

        # 保存 base_results 和 base_eval (from result)
        _write_jsonl(fewshot_dir / "base_results.jsonl", result.base_results)
        _write_jsonl(fewshot_dir / "base_eval.jsonl", result.base_eval_records)

        # 保存 selected_examples
        _write_jsonl(fewshot_dir / "selected_examples.jsonl", result.new_fewshot_examples)
        _write_jsonl(fewshot_dir / "selected_fewshot_with_rationale.jsonl", result.new_fewshot_examples)
        _write_jsonl(fewshot_dir / "candidate_pool.jsonl", result.candidate_pool)
        _write_jsonl(fewshot_dir / "candidate_scores.jsonl", result.candidate_scores)
        _write_jsonl(fewshot_dir / "fewshot_rationale_records.jsonl", result.rationale_records)
        _write_jsonl(fewshot_dir / "fewshot_rationale_trajectory.jsonl", result.rationale_trajectory)

        # 保存 final_results 和 final_eval
        _write_jsonl(fewshot_dir / "final_results.jsonl", result.final_results)
        _write_jsonl(fewshot_dir / "final_eval.jsonl", result.final_eval_records)
        _write_json(fewshot_dir / "validation_report.json", result.validation_report)
        _write_json(fewshot_dir / "decision.json", result.decision)

        # 保存 metrics
        _write_json(fewshot_dir / "metrics.json", result.metrics)

        # 保留旧的 metrics 和 examples 文件（向后兼容）
        _write_json(iteration_dir / "fewshot_metrics.json", result.metrics)
        _write_json(
            iteration_dir / "selected_examples.json",
            [e.to_dict() for e in result.new_fewshot_examples],
        )
        _write_json(iteration_dir / "decision.json", result.decision)

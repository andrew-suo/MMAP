"""Few-shot Optimization Phase。

根据设计文档，Few-shot Optimization Phase 负责优化 few-shot 图文示例。
该 phase 在 Prompt Optimization Phase 之后执行，进入该 phase 后，文本 prompt 被锁定。

每次迭代包含两个 stage：
1. Sampling Stage
2. Few-shot Optimization Stage
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from ..core.artifacts import to_artifact_data, write_json_artifact, write_jsonl_artifact
from ..core.logging import get_logger, log_stage
from ..core.progress import NullProgressReporter, ProgressReporter
from ..stages.extraction_prompt_optimization import ExtractionResult
from ..data.sampler import SamplerConfig, create_sampler
from ..data.sample import SampleBatch, SampleSet, SampleTrace, SampleSpec, SampleState
from ..prompt.structured_prompt import StructuredPrompt


@dataclass
class FewshotExample:
    """Few-shot 示例。"""
    id: str
    sample_id: str
    input_text: str
    output_text: str
    input_images: list[str] = field(default_factory=list)
    output_data: dict[str, Any] = field(default_factory=dict)
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
            metadata=dict(data.get("metadata", {})),
        )


@dataclass
class FewshotConfig:
    """Few-shot Optimization 配置。"""
    enabled: bool = True
    rounds: int = 2
    batch_size: int = 99
    slot_count: int = 5
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
        }


@dataclass
class FewshotOptimizationIterationResult:
    """Few-shot Optimization 单轮迭代结果。"""
    iteration: int
    batch: SampleBatch
    metrics: FewshotMetrics
    old_fewshot_examples: list[FewshotExample]
    new_fewshot_examples: list[FewshotExample]
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """转换为字典格式。"""
        return {
            "iteration": self.iteration,
            "batch_id": self.batch.id,
            "metrics": self.metrics.to_dict(),
            "old_fewshot_examples": [e.to_dict() for e in self.old_fewshot_examples],
            "new_fewshot_examples": [e.to_dict() for e in self.new_fewshot_examples],
            "notes": list(self.notes),
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

        # Stage 2: Few-shot Optimization Stage
        metrics, new_examples = self._fewshot_optimization_stage(iteration, batch)

        # 构造结果
        result = FewshotOptimizationIterationResult(
            iteration=iteration,
            batch=batch,
            metrics=metrics,
            old_fewshot_examples=self.fewshot_examples.copy(),
            new_fewshot_examples=new_examples,
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

    def _fewshot_optimization_stage(
        self,
        iteration: int,
        batch: SampleBatch,
    ) -> tuple[FewshotMetrics, list[FewshotExample]]:
        """Few-shot Optimization Stage。"""
        metrics = FewshotMetrics()

        # Step 1: 抽取
        base_extraction_results = self._execute_extraction(batch)

        # Step 2: 统计结果
        self._compute_base_metrics(batch, base_extraction_results, metrics)

        # Step 3: 选择前 N 个困难样本填入 few-shot 槽位
        new_examples = self._select_difficult_samples(batch, metrics)

        # Step 4: 接受判断
        if new_examples:
            # 使用新的 few-shot set 重新测试
            final_extraction_results = self._execute_extraction_with_fewshot(batch, new_examples)
            self._compute_final_metrics(batch, final_extraction_results, metrics)

            # 判断是否接受
            if metrics.final_accuracy is not None and metrics.base_accuracy is not None:
                metrics.accepted = metrics.final_accuracy >= metrics.base_accuracy
            else:
                metrics.accepted = False
        else:
            metrics.accepted = False

        metrics.selected_example_count = len(new_examples)

        return metrics, new_examples

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
                        trace.base_extraction_status = result.status
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
                    trace.base_extraction_status = result.status

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
                        trace.final_extraction_status = result.status
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
                    trace.final_extraction_status = result.status

        return results

    def _compute_base_metrics(
        self,
        batch: SampleBatch,
        results: list[ExtractionResult],
        metrics: FewshotMetrics,
    ) -> None:
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

            # 更新样本状态
            for result in results:
                state = self.sample_set.states.get(result.sample_id)
                if state:
                    has_error = result.status in ["wrong", "invalid"]
                    state.update_error(has_error)
                    state.last_extraction_status = result.status
            return

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

    def _compute_final_metrics(
        self,
        batch: SampleBatch,
        results: list[ExtractionResult],
        metrics: FewshotMetrics,
    ) -> None:
        """统计最终 few-shot 指标。"""
        if self.fewshot_executor is not None:
            eval_records = self.fewshot_executor.evaluate_results(results, self.sample_set)
            accuracy = self.fewshot_executor.compute_accuracy(eval_records)
            correct_count = sum(1 for r in eval_records if r.correct)
            wrong_count = sum(1 for r in eval_records if r.status == "wrong")
            invalid_count = sum(1 for r in eval_records if r.status == "invalid")
            total = len(eval_records)

            metrics.final_correct_count = correct_count
            metrics.final_wrong_count = wrong_count
            metrics.final_invalid_count = invalid_count
            metrics.final_accuracy = accuracy if total > 0 else 0.0
            return

        correct_count = sum(1 for r in results if r.status == "correct")
        wrong_count = sum(1 for r in results if r.status == "wrong")
        invalid_count = sum(1 for r in results if r.status == "invalid")
        total = len(results)

        metrics.final_correct_count = correct_count
        metrics.final_wrong_count = wrong_count
        metrics.final_invalid_count = invalid_count
        metrics.final_accuracy = correct_count / total if total > 0 else 0.0

    def _select_difficult_samples(
        self,
        batch: SampleBatch,
        metrics: FewshotMetrics,
    ) -> list[FewshotExample]:
        """选择前 N 个困难样本填入 few-shot 槽位。"""
        # 获取本轮样本的困难度排序
        sample_difficulties: list[tuple[str, float]] = []

        for sample_id in batch.sample_ids:
            state = self.sample_set.states.get(sample_id)
            if state:
                sample_difficulties.append((sample_id, state.difficulty_score))

        # 按困难度降序排序
        sample_difficulties.sort(key=lambda x: x[1], reverse=True)

        # 选择前 N 个
        selected_ids = [sid for sid, _ in sample_difficulties[:self.config.slot_count]]

        # 构造 few-shot examples
        examples: list[FewshotExample] = []

        for sample_id in selected_ids:
            spec = self.sample_set.specs.get(sample_id)
            if spec is None:
                continue

            # 构造 example
            example = FewshotExample(
                id=f"fewshot_{sample_id}",
                sample_id=sample_id,
                input_text=str(spec.input),
                input_images=[asset.uri or asset.local_path or "" for asset in spec.assets],
                output_text=str(spec.ground_truth),
                output_data=spec.ground_truth,
            )
            examples.append(example)

        # 如果可用困难样本少于槽位数，从当前 batch 中继续按难度顺序补齐
        if len(examples) < self.config.slot_count:
            remaining_ids = [sid for sid, _ in sample_difficulties[self.config.slot_count:]]
            for sample_id in remaining_ids:
                if len(examples) >= self.config.slot_count:
                    break

                spec = self.sample_set.specs.get(sample_id)
                if spec is None:
                    continue

                example = FewshotExample(
                    id=f"fewshot_{sample_id}",
                    sample_id=sample_id,
                    input_text=str(spec.input),
                    input_images=[asset.uri or asset.local_path or "" for asset in spec.assets],
                    output_text=str(spec.ground_truth),
                    output_data=spec.ground_truth,
                )
                examples.append(example)

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
        write_json_artifact(iteration_dir / "sample_batch.json", result.batch.__dict__)

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
        _write_jsonl(fewshot_dir / "base_results.jsonl", getattr(result, "base_results", []))
        _write_jsonl(fewshot_dir / "base_eval.jsonl", getattr(result, "base_eval_records", []))

        # 保存 selected_examples
        _write_jsonl(fewshot_dir / "selected_examples.jsonl", result.new_fewshot_examples)

        # 保存 final_results 和 final_eval
        _write_jsonl(fewshot_dir / "final_results.jsonl", getattr(result, "final_results", []))
        _write_jsonl(fewshot_dir / "final_eval.jsonl", getattr(result, "final_eval_records", []))

        # 保存 metrics
        _write_json(fewshot_dir / "metrics.json", result.metrics)

        # 保留旧的 metrics 和 examples 文件（向后兼容）
        _write_json(iteration_dir / "fewshot_metrics.json", result.metrics)
        _write_json(
            iteration_dir / "selected_examples.json",
            [e.to_dict() for e in result.new_fewshot_examples],
        )

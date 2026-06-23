"""Prompt Optimization Phase。

根据设计文档，Prompt Optimization Phase 每次迭代包含三个 stage：
1. Sampling Stage
2. Extraction Prompt Optimization Stage
3. Analysis Prompt Optimization Stage
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .analysis_prompt_optimization_stage import AnalysisMetrics, AnalysisPromptOptimizationStage
from .batch_size_controller import BatchSizeController, BatchSizeControllerConfig
from .extraction_prompt_optimization_stage import ExtractionMetrics, ExtractionPromptOptimizationStage
from .sampler import SamplerConfig, create_sampler
from .sample import SampleBatch, SampleSet, SampleTrace
from .structured_prompt import StructuredPrompt


@dataclass
class PromptOptimizationConfig:
    """Prompt Optimization 配置。"""
    enabled: bool = True
    rounds: int = 3
    initial_batch_size: int = 16
    min_batch_size: int = 8
    max_batch_size: int = 99

    # Batch Size Controller
    batch_size_controller: BatchSizeControllerConfig = field(default_factory=BatchSizeControllerConfig)

    # Sampler
    sampler: SamplerConfig = field(default_factory=lambda: SamplerConfig(type="difficulty_frequency"))

    # Extraction Prompt
    extraction_prompt_line_limit: int = 300
    extraction_prompt_char_limit: int = 20000
    extraction_prompt_compression_enabled: bool = True

    # Analysis Prompt
    analysis_prompt_line_limit: int = 250
    analysis_prompt_char_limit: int = 16000
    analysis_prompt_compression_enabled: bool = True

    # Patch
    patch_merge_strategy: str = "tree_merge"
    toxicity_test_enabled: bool = True
    toxicity_test_early_stop: bool = True
    toxicity_test_sort_by_source_difficulty: bool = True


@dataclass
class PromptOptimizationIterationResult:
    """Prompt Optimization 单轮迭代结果。"""
    iteration: int
    batch: SampleBatch
    extraction_metrics: ExtractionMetrics
    analysis_metrics: AnalysisMetrics
    extraction_prompt: StructuredPrompt
    analysis_prompt: StructuredPrompt
    rollback: bool = False
    no_progress: bool = False
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """转换为字典格式。"""
        return {
            "iteration": self.iteration,
            "batch_id": self.batch.id,
            "extraction_metrics": self.extraction_metrics.to_dict(),
            "analysis_metrics": self.analysis_metrics.to_dict(),
            "extraction_prompt_id": self.extraction_prompt.id,
            "analysis_prompt_id": self.analysis_prompt.id,
            "rollback": self.rollback,
            "no_progress": self.no_progress,
            "notes": list(self.notes),
        }


class PromptOptimizationPhase:
    """Prompt Optimization Phase。"""

    def __init__(
        self,
        config: PromptOptimizationConfig,
        extraction_prompt: StructuredPrompt,
        analysis_prompt: StructuredPrompt,
        sample_set: SampleSet,
        output_dir: Path,
        seed: int = 42,
        executors: dict[str, Any] | None = None,
    ):
        self.config = config
        self.extraction_prompt = extraction_prompt
        self.analysis_prompt = analysis_prompt
        self.sample_set = sample_set
        self.output_dir = output_dir
        self.seed = seed
        # executor 字典，默认为空（stage 内部会回退到 mock）
        self.executors = executors or {}

        # 创建 sampler
        self.sampler = create_sampler(config.sampler)

        # 创建 batch size controller
        self.batch_size_controller = BatchSizeController(config.batch_size_controller)

        # 结果存储
        self.iteration_results: list[PromptOptimizationIterationResult] = []

    def run(self) -> list[PromptOptimizationIterationResult]:
        """执行完整的 Prompt Optimization Phase。"""
        if not self.config.enabled:
            return []

        for iteration in range(1, self.config.rounds + 1):
            result = self._run_iteration(iteration)
            self.iteration_results.append(result)

            # 更新 batch size controller
            if result.extraction_metrics.base_accuracy is not None:
                self.batch_size_controller.update(
                    base_accuracy=result.extraction_metrics.base_accuracy,
                    final_accuracy=result.extraction_metrics.final_accuracy,
                    rollback=result.rollback,
                    no_progress=result.no_progress,
                )

        return self.iteration_results

    def _run_iteration(self, iteration: int) -> PromptOptimizationIterationResult:
        """执行单轮迭代。"""
        # Stage 1: Sampling Stage
        batch = self._sampling_stage(iteration)

        # Stage 2: Extraction Prompt Optimization Stage
        extraction_stage = ExtractionPromptOptimizationStage(
            extraction_prompt=self.extraction_prompt,
            analysis_prompt=self.analysis_prompt,
            sample_set=self.sample_set,
            batch=batch,
            iteration=iteration,
            extraction_executor=self.executors.get("extraction"),
            evaluation_executor=self.executors.get("evaluation"),
            analysis_executor=self.executors.get("analysis"),
        )
        extraction_metrics = extraction_stage.run()

        # 更新 extraction prompt（如果有 accepted patches）
        if extraction_stage.final_merged_patches:
            # 这里需要实际应用 patch，第一版使用 mock
            self.extraction_prompt.version += 1
            self.extraction_prompt.metadata["last_iteration"] = iteration

        # Stage 3: Analysis Prompt Optimization Stage
        analysis_stage = AnalysisPromptOptimizationStage(
            analysis_prompt=self.analysis_prompt,
            extraction_results=extraction_stage.base_extraction_results,
            base_analysis_results=extraction_stage.analysis_results,
            sample_set=self.sample_set,
            batch=batch,
            iteration=iteration,
            analysis_executor=self.executors.get("analysis"),
        )
        analysis_metrics = analysis_stage.run()

        # 更新 analysis prompt（如果有 accepted patches）
        if analysis_stage.final_merged_patches:
            self.analysis_prompt.version += 1
            self.analysis_prompt.metadata["last_iteration"] = iteration

        # 构造结果
        rollback = extraction_metrics.rollback or extraction_metrics.no_progress
        no_progress = extraction_metrics.no_progress and analysis_metrics.no_progress

        result = PromptOptimizationIterationResult(
            iteration=iteration,
            batch=batch,
            extraction_metrics=extraction_metrics,
            analysis_metrics=analysis_metrics,
            extraction_prompt=self.extraction_prompt,
            analysis_prompt=self.analysis_prompt,
            rollback=rollback,
            no_progress=no_progress,
        )

        # 保存 artifact
        self._save_iteration_artifacts(iteration, extraction_stage, analysis_stage, result)

        return result

    def _sampling_stage(self, iteration: int) -> SampleBatch:
        """Sampling Stage。"""
        batch_size = self.batch_size_controller.get_current_batch_size()

        batch = self.sampler.sample(
            sample_set=self.sample_set,
            batch_size=batch_size,
            iteration=iteration,
            seed=self.seed,
        )

        # 设置 phase
        batch.phase = "prompt_optimization"

        # 清除该轮次的旧 traces
        self.sample_set.clear_traces_for_iteration("prompt_optimization", iteration)

        # 为每个被选中的样本创建 trace
        for sample_id in batch.sample_ids:
            trace = SampleTrace(
                sample_id=sample_id,
                phase="prompt_optimization",
                iteration=iteration,
                selected=True,
            )
            self.sample_set.add_trace(trace)

        # 为未被选中的样本创建 trace
        active_specs = self.sample_set.get_active_specs()
        for spec in active_specs:
            if spec.id not in batch.sample_ids:
                trace = SampleTrace(
                    sample_id=spec.id,
                    phase="prompt_optimization",
                    iteration=iteration,
                    selected=False,
                )
                self.sample_set.add_trace(trace)

        return batch

    def _save_iteration_artifacts(
        self,
        iteration: int,
        extraction_stage: ExtractionPromptOptimizationStage,
        analysis_stage: AnalysisPromptOptimizationStage,
        result: PromptOptimizationIterationResult,
    ) -> None:
        """保存单轮迭代的 artifacts。"""
        iteration_dir = self.output_dir / f"prompt_iter_{iteration:03d}"
        iteration_dir.mkdir(parents=True, exist_ok=True)

        # 保存 batch
        import json
        (iteration_dir / "sample_batch.json").write_text(
            json.dumps(result.batch.__dict__, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

        # 保存 extraction metrics
        (iteration_dir / "extraction_metrics.json").write_text(
            json.dumps(result.extraction_metrics.to_dict(), indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

        # 保存 analysis metrics
        (iteration_dir / "analysis_metrics.json").write_text(
            json.dumps(result.analysis_metrics.to_dict(), indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

        # 保存 batch size controller state
        (iteration_dir / "batch_size_controller.json").write_text(
            json.dumps(self.batch_size_controller.to_dict(), indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
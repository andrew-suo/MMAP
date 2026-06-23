"""Executor Protocol 接口定义。

根据设计文档，所有 executor 都遵循统一的 Protocol 接口，
便于后续接入真实实现或 Mock 实现。
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Protocol

from ..extraction_prompt_optimization_stage import (
    AnalysisResult,
    EvalRecord,
    ExtractionResult,
)
from ..fewshot_optimization_phase import FewshotExample
from ..patch import (
    AnalysisPatch,
    ExtractionPatch,
    PatchMergeReport,
    ToxicityReport,
)
from ..sample import SampleBatch, SampleSet, SampleSpec, SampleState
from ..structured_prompt import StructuredPrompt

if TYPE_CHECKING:
    # 避免循环导入，仅在类型检查时引用 ReflectionResult
    from ..analysis_prompt_optimization_stage import ReflectionResult


class ExtractionExecutorProtocol(Protocol):
    """抽取执行器接口。"""

    def execute(
        self,
        prompt: StructuredPrompt,
        batch: SampleBatch,
        sample_set: SampleSet,
        fewshot_examples: list[FewshotExample] | None = None,
    ) -> list[ExtractionResult]:
        """执行抽取。"""
        ...


class EvaluationExecutorProtocol(Protocol):
    """评估执行器接口。"""

    def evaluate(
        self,
        extraction_result: ExtractionResult,
        ground_truth: dict[str, Any],
        sample_state: SampleState | None = None,
    ) -> EvalRecord:
        """评估单个抽取结果。"""
        ...

    def evaluate_batch(
        self,
        extraction_results: list[ExtractionResult],
        sample_set: SampleSet,
    ) -> list[EvalRecord]:
        """批量评估抽取结果。"""
        ...


class AnalysisExecutorProtocol(Protocol):
    """分析执行器接口。"""

    def execute(
        self,
        analysis_prompt: StructuredPrompt,
        extraction_prompt: StructuredPrompt,
        extraction_result: ExtractionResult,
        sample_spec: SampleSpec,
    ) -> AnalysisResult:
        """执行单个样本分析。"""
        ...

    def execute_batch(
        self,
        analysis_prompt: StructuredPrompt,
        extraction_prompt: StructuredPrompt,
        extraction_results: list[ExtractionResult],
        sample_set: SampleSet,
    ) -> list[AnalysisResult]:
        """批量执行分析。"""
        ...

    def reflect(
        self,
        analysis_prompt: StructuredPrompt,
        extraction_result: ExtractionResult,
        analysis_result: AnalysisResult,
        sample_spec: SampleSpec,
    ) -> "ReflectionResult":
        """对分析错误样本进行反思。"""
        ...


class PatchGenerationExecutorProtocol(Protocol):
    """Patch 生成执行器接口。"""

    def generate_extraction_patches(
        self,
        analysis_results: list[AnalysisResult],
        extraction_results: list[ExtractionResult],
        extraction_prompt: StructuredPrompt,
        sample_set: SampleSet,
    ) -> list[ExtractionPatch]:
        """生成 extraction patch。"""
        ...

    def generate_analysis_patches(
        self,
        reflection_results: list,
        analysis_prompt: StructuredPrompt,
        sample_set: SampleSet,
    ) -> list[AnalysisPatch]:
        """生成 analysis patch。"""
        ...


class PatchApplyExecutorProtocol(Protocol):
    """Patch 应用执行器接口。"""

    def apply(
        self,
        base_prompt: StructuredPrompt,
        patches: list,
    ) -> tuple[StructuredPrompt, dict[str, Any]]:
        """应用 patch 到 prompt。"""
        ...


class MergeExecutorProtocol(Protocol):
    """Patch 合并执行器接口。"""

    def merge(
        self,
        patches: list,
        prompt: StructuredPrompt,
        merge_strategy: str = "tree_merge",
    ) -> tuple[list, PatchMergeReport]:
        """合并 patches。"""
        ...


class ToxicityTestExecutorProtocol(Protocol):
    """测毒执行器接口。"""

    def test(
        self,
        base_prompt: StructuredPrompt,
        candidate_patches: list,
        toxic_sample_ids: list[str],
        sample_set: SampleSet,
        extraction_executor: Any = None,
        evaluation_executor: Any = None,
        early_stop: bool = True,
    ) -> tuple[list, list, ToxicityReport]:
        """执行测毒测试。"""
        ...


class CompressionExecutorProtocol(Protocol):
    """压缩执行器接口。"""

    def compress_if_needed(
        self,
        prompt: StructuredPrompt,
        line_limit: int,
        char_limit: int,
        batch: SampleBatch,
        sample_set: SampleSet,
        extraction_executor: Any = None,
        evaluation_executor: Any = None,
    ) -> tuple[StructuredPrompt, dict[str, Any]]:
        """按需压缩 prompt。"""
        ...


class FewshotExecutorProtocol(Protocol):
    """Few-shot 执行器接口。"""

    def execute_extraction(
        self,
        extraction_prompt: StructuredPrompt,
        fewshot_examples: list[FewshotExample],
        batch: SampleBatch,
        sample_set: SampleSet,
    ) -> list[ExtractionResult]:
        """使用 few-shot 执行抽取。"""
        ...

    def execute_validation(
        self,
        extraction_prompt: StructuredPrompt,
        fewshot_examples: list[FewshotExample],
        batch: SampleBatch,
        sample_set: SampleSet,
    ) -> list[ExtractionResult]:
        """使用 few-shot 执行验证。"""
        ...


__all__ = [
    "ExtractionExecutorProtocol",
    "EvaluationExecutorProtocol",
    "AnalysisExecutorProtocol",
    "PatchGenerationExecutorProtocol",
    "PatchApplyExecutorProtocol",
    "MergeExecutorProtocol",
    "ToxicityTestExecutorProtocol",
    "CompressionExecutorProtocol",
    "FewshotExecutorProtocol",
]

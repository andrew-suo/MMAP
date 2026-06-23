"""Executor 工厂函数。

根据配置创建所有 executor 实例。第一版返回 Mock 实现，
后续 PR 再接入真实实现。
"""

from __future__ import annotations

from typing import Any

from ..stages.extraction_prompt_optimization import (
    AnalysisResult,
    EvalRecord,
    ExtractionResult,
)
from ..phases.fewshot_optimization import FewshotExample
from ..patch.types import (
    AnalysisPatch,
    ExtractionPatch,
    PatchMergeReport,
    ToxicityReport,
)
from ..data.sample import SampleBatch, SampleSet, SampleSpec, SampleState
from ..prompt.structured_prompt import StructuredPrompt
from .analysis_executor import AnalysisExecutor
from .compression_executor import CompressionExecutor
from .evaluation_executor import EvaluationExecutor
from .extraction_executor import ExtractionExecutor
from .fewshot_executor import FewshotExecutor
from .patch_apply_executor import PatchApplyExecutor
from .patch_generation_executor import PatchGenerationExecutor
from .patch_validator import PatchValidator
from .merge_executor import MergeExecutor
from .toxicity_executor import ToxicityTestExecutor
from .interfaces import (
    AnalysisExecutorProtocol,
    CompressionExecutorProtocol,
    EvaluationExecutorProtocol,
    ExtractionExecutorProtocol,
    FewshotExecutorProtocol,
    MergeExecutorProtocol,
    PatchApplyExecutorProtocol,
    PatchGenerationExecutorProtocol,
    ToxicityTestExecutorProtocol,
)


class _MockExtractionExecutor:
    """Mock 抽取执行器。"""

    def execute(
        self,
        prompt: StructuredPrompt,
        batch: SampleBatch,
        sample_set: SampleSet,
        fewshot_examples: list[FewshotExample] | None = None,
    ) -> list[ExtractionResult]:
        results: list[ExtractionResult] = []
        for sample_id in batch.sample_ids:
            results.append(
                ExtractionResult(
                    sample_id=sample_id,
                    raw_output="mock output",
                    parsed_output={"mock": "data"},
                    status="correct",
                )
            )
        return results


class _MockEvaluationExecutor:
    """Mock 评估执行器。"""

    def evaluate(
        self,
        extraction_result: ExtractionResult,
        ground_truth: dict[str, Any],
        sample_state: SampleState | None = None,
    ) -> EvalRecord:
        return EvalRecord(
            sample_id=extraction_result.sample_id,
            extraction_result_id=extraction_result.sample_id,
            status=extraction_result.status,
            correct=extraction_result.status == "correct",
        )

    def evaluate_batch(
        self,
        extraction_results: list[ExtractionResult],
        sample_set: SampleSet,
    ) -> list[EvalRecord]:
        records: list[EvalRecord] = []
        for result in extraction_results:
            spec = sample_set.specs.get(result.sample_id)
            ground_truth = spec.ground_truth if spec is not None else {}
            records.append(self.evaluate(result, ground_truth))
        return records


class _MockAnalysisExecutor:
    """Mock 分析执行器。"""

    def execute(
        self,
        analysis_prompt: StructuredPrompt,
        extraction_prompt: StructuredPrompt,
        extraction_result: ExtractionResult,
        sample_spec: SampleSpec,
    ) -> AnalysisResult:
        return AnalysisResult(
            sample_id=extraction_result.sample_id,
            judgement={"mock": "judgement"},
            analysis_correct=True,
        )

    def execute_batch(
        self,
        analysis_prompt: StructuredPrompt,
        extraction_prompt: StructuredPrompt,
        extraction_results: list[ExtractionResult],
        sample_set: SampleSet,
    ) -> list[AnalysisResult]:
        results: list[AnalysisResult] = []
        for extraction_result in extraction_results:
            spec = sample_set.specs.get(extraction_result.sample_id)
            if spec is None:
                continue
            results.append(
                self.execute(analysis_prompt, extraction_prompt, extraction_result, spec)
            )
        return results

    def reflect(
        self,
        analysis_prompt: StructuredPrompt,
        extraction_result: ExtractionResult,
        analysis_result: AnalysisResult,
        sample_spec: SampleSpec,
    ) -> Any:
        # 延迟导入以避免循环依赖
        from ..stages.analysis_prompt_optimization import ReflectionResult

        return ReflectionResult(
            sample_id=extraction_result.sample_id,
            reflection_success=True,
            error_reason="Mock reflection",
        )


class _MockPatchGenerationExecutor:
    """Mock patch 生成执行器。"""

    def generate_extraction_patches(
        self,
        analysis_results: list[AnalysisResult],
        extraction_results: list[ExtractionResult],
        extraction_prompt: StructuredPrompt,
        sample_set: SampleSet,
    ) -> list[ExtractionPatch]:
        patches: list[ExtractionPatch] = []
        for analysis_result in analysis_results:
            if not analysis_result.analysis_correct:
                continue
            patches.append(
                ExtractionPatch(
                    id=f"patch_extraction_{analysis_result.sample_id}",
                    target_section_id="section_1",
                    operation_type="replace",
                    content="Mock patch content",
                    rationale="Mock rationale",
                    source_sample_ids=[analysis_result.sample_id],
                    status="draft",
                )
            )
        return patches

    def generate_analysis_patches(
        self,
        reflection_results: list,
        analysis_prompt: StructuredPrompt,
        sample_set: SampleSet,
    ) -> list[AnalysisPatch]:
        patches: list[AnalysisPatch] = []
        for reflection in reflection_results:
            patches.append(
                AnalysisPatch(
                    id=f"patch_analysis_{getattr(reflection, 'sample_id', 'unknown')}",
                    target_section_id="section_1",
                    operation_type="replace",
                    content="Mock analysis patch content",
                    rationale="Mock rationale",
                    source_sample_ids=[getattr(reflection, "sample_id", "unknown")],
                    status="draft",
                )
            )
        return patches


class _MockPatchApplyExecutor:
    """Mock patch 应用执行器。"""

    def apply(
        self,
        base_prompt: StructuredPrompt,
        patches: list,
    ) -> tuple[StructuredPrompt, dict[str, Any]]:
        # Mock：直接返回原 prompt
        return base_prompt, {"applied_patch_count": len(patches)}


class _MockMergeExecutor:
    """Mock patch 合并执行器。"""

    def merge(
        self,
        patches: list,
        prompt: StructuredPrompt,
        merge_strategy: str = "tree_merge",
    ) -> tuple[list, PatchMergeReport]:
        report = PatchMergeReport(
            id=f"merge_report_{merge_strategy}",
            input_patch_count=len(patches),
            merged_patch_count=len(patches),
            conflict_count=0,
        )
        return list(patches), report


class _MockToxicityTestExecutor:
    """Mock 测毒执行器。"""

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
        safe_patches = list(candidate_patches)
        toxic_patches: list = []
        report = ToxicityReport(
            id="toxicity_report_mock",
            tested_patch_count=len(candidate_patches),
            toxic_patch_count=0,
            safe_patch_count=len(safe_patches),
            toxic_sample_ids=list(toxic_sample_ids),
        )
        return safe_patches, toxic_patches, report


class _MockCompressionExecutor:
    """Mock 压缩执行器。"""

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
        # Mock：不压缩，直接返回原 prompt
        return prompt, {"compressed": False, "line_limit": line_limit, "char_limit": char_limit}


class _MockFewshotExecutor:
    """Mock few-shot 执行器。"""

    def execute_extraction(
        self,
        extraction_prompt: StructuredPrompt,
        fewshot_examples: list[FewshotExample],
        batch: SampleBatch,
        sample_set: SampleSet,
    ) -> list[ExtractionResult]:
        results: list[ExtractionResult] = []
        for sample_id in batch.sample_ids:
            results.append(
                ExtractionResult(
                    sample_id=sample_id,
                    raw_output="mock fewshot output",
                    parsed_output={"mock": "fewshot_data"},
                    status="correct",
                )
            )
        return results

    def execute_validation(
        self,
        extraction_prompt: StructuredPrompt,
        fewshot_examples: list[FewshotExample],
        batch: SampleBatch,
        sample_set: SampleSet,
    ) -> list[ExtractionResult]:
        return self.execute_extraction(
            extraction_prompt, fewshot_examples, batch, sample_set
        )

    def evaluate_results(
        self,
        extraction_results: list[ExtractionResult],
        sample_set: SampleSet,
    ) -> list[EvalRecord]:
        """评估抽取结果（mock 实现，复用 _MockEvaluationExecutor 逻辑）。"""
        mock_eval = _MockEvaluationExecutor()
        return mock_eval.evaluate_batch(extraction_results, sample_set)

    def compute_accuracy(self, eval_records: list[EvalRecord]) -> float:
        """计算准确率：correct_count / total_count。"""
        total = len(eval_records)
        if total == 0:
            return 0.0
        correct_count = sum(1 for r in eval_records if r.correct)
        return correct_count / total


def _build_model_client(model_config: dict[str, Any] | None) -> Any:
    """根据 model 配置构建 ModelClient。

    第一版仅返回 None，后续 PR 接入真实 ModelClient。
    """
    if not model_config:
        return None
    try:
        from ..core.config import ModelConfig, model_config_from_mapping
        from ..model.factory import build_model_client
    except Exception:
        return None
    try:
        config = model_config_from_mapping(model_config)
        return build_model_client(config)
    except Exception:
        return None


def create_executors(
    config: dict[str, Any],
    use_mock: bool | None = None,
) -> dict[str, Any]:
    """从配置创建所有 executor 实例。

    PR4 Mock 边界收敛：
    - ``use_mock=True``：强制使用 mock executor（用于单元测试 / 无 model_client 的本地开发）。
    - ``use_mock=False``：强制使用真实 executor；若 model_client 不可用则抛出 RuntimeError。
    - ``use_mock=None``（默认）：自动判断，有 model_client 则真实，否则 mock。

    Args:
        config: 配置字典，可包含 ``models`` 子配置。
        use_mock: 是否强制使用 mock executor。

    Returns:
        包含所有 executor 实例的字典，键为 executor 名称：
        - ``extraction``: 抽取执行器
        - ``evaluation``: 评估执行器
        - ``analysis``: 分析执行器
        - ``patch_generation``: patch 生成执行器
        - ``patch_apply``: patch 应用执行器
        - ``merge``: patch 合并执行器
        - ``toxicity_test``: 测毒执行器
        - ``compression``: 压缩执行器
        - ``fewshot``: few-shot 执行器
        - ``model_client``: 模型客户端（可能为 None）
    """
    models_config = config.get("models", {}) if isinstance(config, dict) else {}
    extraction_model_config = models_config.get("extraction") if isinstance(models_config, dict) else None
    optimizer_model_config = models_config.get("optimizer") if isinstance(models_config, dict) else None

    model_client = _build_model_client(extraction_model_config or optimizer_model_config)

    # PR4: 根据 use_mock 决定是否使用真实 executor
    # use_mock=False 且 model_client 不可用时，直接报错（不允许 fallback 到 mock）
    if use_mock is False and model_client is None:
        raise RuntimeError(
            "use_mock=false 但 model_client 不可用。"
            "请配置有效的 models.* 配置，或显式设置 use_mock=true 以使用 mock 模式。"
        )

    # 当 model_client 可用且未强制 mock 时，使用真实 executor
    use_real = model_client is not None and use_mock is not True
    if use_real:
        extraction_executor: Any = ExtractionExecutor(model_client, extraction_model_config)
        evaluation_executor: Any = EvaluationExecutor()
        analysis_executor: Any = AnalysisExecutor(model_client, optimizer_model_config)
        fewshot_executor: Any = FewshotExecutor(model_client, extraction_model_config)
    else:
        extraction_executor = _MockExtractionExecutor()
        evaluation_executor = _MockEvaluationExecutor()
        analysis_executor = _MockAnalysisExecutor()
        fewshot_executor = _MockFewshotExecutor()

    return {
        "extraction": extraction_executor,
        "evaluation": evaluation_executor,
        "analysis": analysis_executor,
        "patch_generation": PatchGenerationExecutor(),
        "patch_apply": PatchApplyExecutor(),
        "patch_validator": PatchValidator(),
        "merge": MergeExecutor(),
        "toxicity_test": ToxicityTestExecutor(),
        "compression": CompressionExecutor(model_client=model_client),
        "fewshot": fewshot_executor,
        "model_client": model_client,
    }


__all__ = [
    "create_executors",
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

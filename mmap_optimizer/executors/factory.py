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

    无配置时返回 None；有配置但构建失败时向上抛出，避免自动模式静默降级。
    """
    if not model_config:
        return None
    from ..core.config import model_config_from_mapping
    from ..model.factory import build_model_client

    config = model_config_from_mapping(model_config)
    return build_model_client(config)


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
        - ``extraction``: 抽取执行器（使用 extraction_client）
        - ``evaluation``: 评估执行器
        - ``analysis``: 分析执行器（使用 optimizer_client）
        - ``patch_generation``: patch 生成执行器（使用 optimizer_client）
        - ``patch_apply``: patch 应用执行器（使用 optimizer_client）
        - ``merge``: patch 合并执行器（使用 optimizer_client）
        - ``toxicity_test``: 测毒执行器
        - ``compression``: 压缩执行器（使用 optimizer_client）
        - ``fewshot``: few-shot 执行器（使用 extraction_client）
        - ``model_client``: 任意可用模型客户端（向后兼容，可能为 None）
        - ``extraction_model_client``: 抽取模型客户端（用于 extraction/fewshot）
        - ``optimizer_model_client``: 优化模型客户端（用于其他所有任务）
    """
    models_config = config.get("models", {}) if isinstance(config, dict) else {}
    extraction_model_config = models_config.get("extraction") if isinstance(models_config, dict) else None
    optimizer_model_config = models_config.get("optimizer") if isinstance(models_config, dict) else None

    # 构建两个独立的 model_client：
    # - extraction_client: 用于抽取和 few-shot 验证
    # - optimizer_client: 用于其他所有任务（分析、patch 生成、压缩、标准化等）
    extraction_client = None
    optimizer_client = None
    if use_mock is not True:
        if extraction_model_config:
            try:
                extraction_client = _build_model_client(extraction_model_config)
            except Exception as e:
                raise RuntimeError(f"extraction model_client 构建失败: {e}") from e
        if optimizer_model_config:
            try:
                optimizer_client = _build_model_client(optimizer_model_config)
            except Exception as e:
                raise RuntimeError(f"optimizer model_client 构建失败: {e}") from e

    # 兜底：只配置了一个模型时两者共用
    if extraction_client is None and optimizer_client is not None:
        extraction_client = optimizer_client
    if optimizer_client is None and extraction_client is not None:
        optimizer_client = extraction_client

    # 向后兼容：model_client 指向任意可用 client（用于校验和旧代码）
    model_client = extraction_client or optimizer_client

    # PR4: 根据 use_mock 决定是否使用真实 executor
    # use_mock=False 且 model_client 不可用时，直接报错（不允许 fallback 到 mock）
    if use_mock is False and model_client is None:
        raise RuntimeError(
            "use_mock=false 但 model_client 不可用。"
            "请配置有效的 models.* 配置，或显式设置 use_mock=true 以使用 mock 模式。"
        )

    prompts_config = config.get("prompts", {}) if isinstance(config, dict) else {}
    analysis_reflection_template_path = prompts_config.get("analysis_reflection")
    patch_generation_prompt_path = prompts_config.get("patch_generation")
    semantic_patch_generation_prompt_path = prompts_config.get("semantic_patch_generation")
    semantic_patch_translation_prompt_path = prompts_config.get("semantic_patch_translation")
    patch_calibration_prompt_path = prompts_config.get("patch_calibration")
    patch_merge_prompt_path = prompts_config.get("patch_merge")
    patch_root_merge_prompt_path = prompts_config.get("patch_root_merge")
    patch_text_match_prompt_path = prompts_config.get("patch_text_match")
    prompt_compression_path = prompts_config.get("prompt_compression", "prompts/prompt_compression.txt")
    prompt_compression_validation_path = prompts_config.get(
        "prompt_compression_validation", "prompts/prompt_compression_validation.txt"
    )
    ema_alpha = config.get("prompt_optimization", {}).get("ema_alpha", 0.3) if isinstance(config, dict) else 0.3
    patch_config = config.get("prompt_optimization", {}).get("patch", {}) if isinstance(config, dict) else {}
    patch_generation_mode = patch_config.get("generation_mode", "semantic_then_translate")

    # 当 model_client 可用且未强制 mock 时，使用真实 executor
    # - extraction/fewshot 用 extraction_client
    # - analysis/patch/merge/compression 用 optimizer_client
    use_real = model_client is not None and use_mock is not True
    if use_real:
        extraction_executor: Any = ExtractionExecutor(extraction_client, extraction_model_config)
        evaluation_executor: Any = EvaluationExecutor()
        analysis_executor: Any = AnalysisExecutor(
            optimizer_client,
            optimizer_model_config,
            analysis_reflection_template_path=analysis_reflection_template_path,
        )
        fewshot_executor: Any = FewshotExecutor(extraction_client, extraction_model_config)
    else:
        extraction_executor = _MockExtractionExecutor()
        evaluation_executor = _MockEvaluationExecutor()
        analysis_executor = _MockAnalysisExecutor()
        fewshot_executor = _MockFewshotExecutor()

    shared_patch_validator = PatchValidator(
        model_client=optimizer_client,
        model_config=optimizer_model_config,
        calibration_prompt_path=patch_calibration_prompt_path,
    )

    patch_generation_executor: Any = PatchGenerationExecutor(
        model_client=optimizer_client,
        model_config=optimizer_model_config,
        patch_generation_prompt_path=patch_generation_prompt_path,
        semantic_patch_generation_prompt_path=semantic_patch_generation_prompt_path or "prompts/semantic_patch_generation.txt",
        patch_translation_prompt_path=semantic_patch_translation_prompt_path or "prompts/semantic_patch_translation.txt",
        patch_generation_mode=patch_generation_mode,
        patch_validator=shared_patch_validator,
    )

    return {
        "extraction": extraction_executor,
        "evaluation": evaluation_executor,
        "analysis": analysis_executor,
        "patch_generation": patch_generation_executor,
        "patch_apply": PatchApplyExecutor(
            model_client=optimizer_client,
            model_config=optimizer_model_config,
            text_match_prompt_path=patch_text_match_prompt_path,
        ),
        "patch_validator": shared_patch_validator,
        "merge": MergeExecutor(
            patch_validator=shared_patch_validator,
            model_client=optimizer_client,
            model_config=optimizer_model_config,
            merge_prompt_path=patch_merge_prompt_path,
            root_merge_prompt_path=patch_root_merge_prompt_path,
        ),
        "toxicity_test": ToxicityTestExecutor(),
        "compression": CompressionExecutor(
            model_client=optimizer_client,
            model_config=optimizer_model_config,
            compression_prompt_path=prompt_compression_path,
            validation_prompt_path=prompt_compression_validation_path,
            ema_alpha=ema_alpha,
        ),
        "fewshot": fewshot_executor,
        "model_client": model_client,
        "extraction_model_client": extraction_client,
        "optimizer_model_client": optimizer_client,
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

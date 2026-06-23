"""FewshotExecutor - 真实 few-shot 执行器，使用真实模型调用和 evaluator。

替代系统中 few-shot phase 的 mock 抽取与验证
（硬编码 ``raw_output="mock fewshot output"``、``status="correct"``），
通过复用 ``ExtractionExecutor`` 与 ``EvaluationExecutor`` 执行真实的模型调用与评估。
"""

from __future__ import annotations

from typing import Any

from ..model.client import ModelClient
from ..stages.extraction_prompt_optimization import EvalRecord, ExtractionResult
from ..phases.fewshot_optimization import FewshotExample
from ..data.sample import SampleBatch, SampleSet
from ..prompt.structured_prompt import StructuredPrompt
from .evaluation_executor import EvaluationExecutor
from .extraction_executor import ExtractionExecutor


class FewshotExecutor:
    """真实 few-shot 执行器，使用真实模型调用和 evaluator。"""

    def __init__(
        self,
        model_client: ModelClient,
        model_config: dict[str, Any] | None = None,
        primary_answer_fields: list[str] | None = None,
        label_mapping: dict[str, Any] | None = None,
        ema_alpha: float = 0.3,
    ):
        self.model_client = model_client
        self.model_config = model_config or {}
        self.primary_answer_fields = primary_answer_fields or ["result"]
        self.label_mapping = label_mapping
        self.ema_alpha = ema_alpha
        # 复用 ExtractionExecutor 的核心逻辑
        self._extraction_executor = ExtractionExecutor(
            model_client=model_client,
            model_config=model_config,
        )
        # 复用 EvaluationExecutor
        self._evaluation_executor = EvaluationExecutor(
            primary_answer_fields=primary_answer_fields,
            label_mapping=label_mapping,
            ema_alpha=ema_alpha,
        )

    def execute_extraction(
        self,
        extraction_prompt: StructuredPrompt,
        fewshot_examples: list[FewshotExample],
        batch: SampleBatch,
        sample_set: SampleSet,
    ) -> list[ExtractionResult]:
        """使用 locked extraction prompt + 当前 few-shot set 真实抽取。"""
        return self._extraction_executor.execute(
            extraction_prompt,
            batch,
            sample_set,
            fewshot_examples,
        )

    def execute_validation(
        self,
        extraction_prompt: StructuredPrompt,
        fewshot_examples: list[FewshotExample],
        batch: SampleBatch,
        sample_set: SampleSet,
    ) -> list[ExtractionResult]:
        """使用新 few-shot set 重新抽取。"""
        return self._extraction_executor.execute(
            extraction_prompt,
            batch,
            sample_set,
            fewshot_examples,
        )

    def evaluate_results(
        self,
        extraction_results: list[ExtractionResult],
        sample_set: SampleSet,
    ) -> list[EvalRecord]:
        """评估抽取结果。"""
        return self._evaluation_executor.evaluate_batch(extraction_results, sample_set)

    def compute_accuracy(self, eval_records: list[EvalRecord]) -> float:
        """计算准确率：correct_count / total_count。"""
        total = len(eval_records)
        if total == 0:
            return 0.0
        correct_count = sum(1 for r in eval_records if r.correct)
        return correct_count / total


__all__ = ["FewshotExecutor"]

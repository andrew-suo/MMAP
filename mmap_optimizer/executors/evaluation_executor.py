"""EvaluationExecutor：真实评估执行器，实现字段级 exact match。

替换 mock 评估逻辑（硬编码 status="correct"），对 ExtractionResult 与
GroundTruth 做字段级比较，产出 EvalRecord，并更新 SampleState 的
error_ema / difficulty_score / last_extraction_status。
"""

from __future__ import annotations

from typing import Any

from ..extraction_prompt_optimization_stage import EvalRecord, ExtractionResult
from ..sample import SampleSet, SampleState


def normalize_label(value: Any, mapping: dict[str, Any] | None = None) -> Any:
    """标签归一化（内联自 evaluation.evaluator.normalize_label）。"""
    if mapping is None:
        mapping = {"合格": "OK", "正常": "OK", "不合格": "NG", "异常": "NG", "无法确认": "UNCERTAIN", "不确定": "UNCERTAIN"}
    if isinstance(value, str):
        return mapping.get(value, mapping.get(value.upper(), value.upper()))
    return value


class EvaluationExecutor:
    """真实评估执行器，实现字段级 exact match。"""

    def __init__(
        self,
        primary_answer_fields: list[str] | None = None,
        label_mapping: dict[str, Any] | None = None,
        ema_alpha: float = 0.3,
    ):
        self.primary_answer_fields = primary_answer_fields or ["result"]
        self.label_mapping = label_mapping
        self.ema_alpha = ema_alpha

    def evaluate(
        self,
        extraction_result: ExtractionResult,
        ground_truth: dict[str, Any],
        sample_state: SampleState | None = None,
    ) -> EvalRecord:
        """评估单个抽取结果。"""
        # 1. parsed_output 为 None → invalid
        if extraction_result.parsed_output is None:
            status = "invalid"
            details: dict[str, Any] = {"reason": "parsed_output is None"}
            self._update_sample_state(sample_state, status)
            return EvalRecord(
                sample_id=extraction_result.sample_id,
                extraction_result_id=extraction_result.sample_id,
                status=status,
                correct=False,
                details=details,
            )

        # 2. 字段级 exact match（支持 normalize）
        parsed_output = extraction_result.parsed_output
        field_results: list[dict[str, Any]] = []
        mismatched_fields: list[str] = []
        all_match = True

        for field in self.primary_answer_fields:
            actual = parsed_output.get(field)
            expected = ground_truth.get(field)
            norm_actual = normalize_label(actual, self.label_mapping)
            norm_expected = normalize_label(expected, self.label_mapping)
            matched = norm_actual == norm_expected
            field_results.append(
                {
                    "field": field,
                    "expected": expected,
                    "actual": actual,
                    "normalized_expected": norm_expected,
                    "normalized_actual": norm_actual,
                    "match": matched,
                }
            )
            if not matched:
                mismatched_fields.append(field)
                all_match = False

        # 3. 所有字段匹配 → correct；任一不匹配 → wrong
        status = "correct" if all_match else "wrong"
        details = {
            "field_results": field_results,
            "mismatched_fields": mismatched_fields,
        }

        # 4. 更新 SampleState
        self._update_sample_state(sample_state, status)

        return EvalRecord(
            sample_id=extraction_result.sample_id,
            extraction_result_id=extraction_result.sample_id,
            status=status,
            correct=(status == "correct"),
            details=details,
        )

    def evaluate_batch(
        self,
        extraction_results: list[ExtractionResult],
        sample_set: SampleSet,
    ) -> list[EvalRecord]:
        """批量评估抽取结果。"""
        results: list[EvalRecord] = []
        for er in extraction_results:
            spec = sample_set.specs.get(er.sample_id)
            if spec is None:
                continue
            state = sample_set.states.get(er.sample_id)
            eval_record = self.evaluate(er, spec.ground_truth, state)
            results.append(eval_record)
        return results

    def _update_sample_state(
        self,
        sample_state: SampleState | None,
        status: str,
    ) -> None:
        """更新 SampleState 的 error_ema、difficulty_score 和 last_extraction_status。"""
        if sample_state is None:
            return
        has_error = status in ["wrong", "invalid"]
        sample_state.update_error(has_error, self.ema_alpha)
        sample_state.last_extraction_status = status


__all__ = ["EvaluationExecutor"]

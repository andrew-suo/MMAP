"""Analysis Executor 真实实现。

接入旧系统 ``ModelClient``，替换 mock 分析执行器。
对 extraction result 执行 analysis，产出 ``AnalysisResult``，
并支持对分析错误样本进行反思，产出 ``ReflectionResult``。
"""

from __future__ import annotations

import json
from typing import Any

from ..model.client import ModelClient

from ..stages.extraction_prompt_optimization import AnalysisResult, ExtractionResult
from ..data.sample import SampleSet, SampleSpec
from ..prompt.structured_prompt import StructuredPrompt, StructuredPromptRenderer
from ..prompt.prompt_manager import render_prompt
from ..prompt.output_repair import repair_json_output
from .evaluation_executor import normalize_label


class AnalysisExecutor:
    """真实分析执行器，接入 ModelClient。"""

    def __init__(
        self,
        model_client: ModelClient,
        model_config: dict[str, Any] | None = None,
        primary_answer_fields: list[str] | None = None,
        label_mapping: dict[str, Any] | None = None,
        analysis_task_template_path: str | None = None,
        analysis_reflection_template_path: str | None = None,
    ):
        self.model_client = model_client
        self.model_config = model_config or {}
        self.primary_answer_fields = primary_answer_fields or ["result"]
        self.label_mapping = label_mapping
        self.renderer = StructuredPromptRenderer()
        self.analysis_task_template_path = analysis_task_template_path
        self.analysis_reflection_template_path = analysis_reflection_template_path

    def execute(
        self,
        analysis_prompt: StructuredPrompt,
        extraction_prompt: StructuredPrompt,
        extraction_result: ExtractionResult,
        sample_spec: SampleSpec,
    ) -> AnalysisResult:
        """对单个样本执行 analysis。"""
        messages = self._build_analysis_messages(
            analysis_prompt, extraction_prompt, extraction_result, sample_spec
        )
        response = self.model_client.complete(messages, model_config=self.model_config)
        judgement = self._parse_judgement(response.raw_output)

        actual_correct = self._compute_actual_correct(
            extraction_result, sample_spec.ground_truth
        )
        analysis_judged = self._extract_analysis_judgement(judgement)
        analysis_correct = (
            analysis_judged == actual_correct if analysis_judged is not None else False
        )

        error_reason = self._extract_error_reason(judgement)
        patch_suggestion: dict[str, Any] | None = None
        # extraction 错误且 analysis 正确识别时生成 patch_suggestion
        if not actual_correct and analysis_correct:
            patch_suggestion = self._build_patch_suggestion(judgement, error_reason)

        return AnalysisResult(
            sample_id=extraction_result.sample_id,
            judgement=judgement,
            analysis_correct=analysis_correct,
            error_reason=error_reason,
            patch_suggestion=patch_suggestion,
        )

    def execute_batch(
        self,
        analysis_prompt: StructuredPrompt,
        extraction_prompt: StructuredPrompt,
        extraction_results: list[ExtractionResult],
        sample_set: SampleSet,
    ) -> list[AnalysisResult]:
        """对 batch 中所有样本执行 analysis（不只错误样本）。"""
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
    ) -> "ReflectionResult":
        """对分析错误的样本进行反思。"""
        # 延迟导入以避免循环依赖
        from ..stages.analysis_prompt_optimization import ReflectionResult

        messages = self._build_reflection_messages(
            analysis_prompt, extraction_result, analysis_result, sample_spec
        )
        response = self.model_client.complete(messages, model_config=self.model_config)
        parsed = self._parse_judgement(response.raw_output)

        error_reason = (
            self._extract_error_reason(parsed)
            or analysis_result.error_reason
            or "analysis misjudged extraction correctness"
        )

        patch_suggestion = self._extract_patch_suggestion(parsed)
        if patch_suggestion is None:
            patch_suggestion = {
                "target_section": "section_1",
                "operation": "replace",
                "content": error_reason,
                "rationale": f"reflection for sample {extraction_result.sample_id}",
            }

        notes = self._extract_notes(parsed)
        reflection_success = bool(parsed)

        return ReflectionResult(
            sample_id=extraction_result.sample_id,
            reflection_success=reflection_success,
            error_reason=error_reason,
            patch_suggestion=patch_suggestion,
            notes=notes,
        )

    def _build_analysis_messages(
        self,
        analysis_prompt: StructuredPrompt,
        extraction_prompt: StructuredPrompt,
        extraction_result: ExtractionResult,
        sample_spec: SampleSpec,
    ) -> list[dict[str, Any]]:
        """构建 analysis 消息。"""
        system_content = self.renderer.render_system_message(analysis_prompt)
        extraction_prompt_text = self.renderer.render(extraction_prompt)

        parsed_output_text = (
            json.dumps(extraction_result.parsed_output, ensure_ascii=False)
            if extraction_result.parsed_output is not None
            else "null"
        )

        error_details = (
            f"error_details: {json.dumps(extraction_result.error_details, ensure_ascii=False)}"
            if extraction_result.error_details
            else ""
        )

        sample_metadata = (
            f"# Sample Metadata\n{json.dumps(sample_spec.metadata, ensure_ascii=False, indent=2)}"
            if sample_spec.metadata
            else ""
        )

        if self.analysis_task_template_path:
            user_content = render_prompt(
                self.analysis_task_template_path,
                extraction_prompt=extraction_prompt_text,
                sample_id=extraction_result.sample_id,
                status=extraction_result.status,
                raw_output=extraction_result.raw_output,
                parsed_output=parsed_output_text,
                error_details=error_details,
                sample_input=json.dumps(sample_spec.input, ensure_ascii=False, indent=2),
                sample_metadata=sample_metadata,
                ground_truth=json.dumps(sample_spec.ground_truth, ensure_ascii=False, indent=2),
            )
        else:
            user_parts: list[str] = []
            user_parts.append("# Extraction Prompt (for reference)")
            user_parts.append(extraction_prompt_text)
            user_parts.append("")
            user_parts.append("# Extraction Result")
            user_parts.append(f"sample_id: {extraction_result.sample_id}")
            user_parts.append(f"status: {extraction_result.status}")
            user_parts.append(f"raw_output: {extraction_result.raw_output}")
            user_parts.append(f"parsed_output: {parsed_output_text}")
            if extraction_result.error_details:
                user_parts.append(
                    f"error_details: {json.dumps(extraction_result.error_details, ensure_ascii=False)}"
                )
            user_parts.append("")
            user_parts.append("# Sample Input")
            user_parts.append(json.dumps(sample_spec.input, ensure_ascii=False, indent=2))
            if sample_spec.metadata:
                user_parts.append("")
                user_parts.append("# Sample Metadata")
                user_parts.append(
                    json.dumps(sample_spec.metadata, ensure_ascii=False, indent=2)
                )
            user_parts.append("")
            user_parts.append("# Ground Truth")
            user_parts.append(
                json.dumps(sample_spec.ground_truth, ensure_ascii=False, indent=2)
            )
            user_parts.append("")
            user_parts.append("# Task")
            user_parts.append(
                "Analyze whether the extraction result is correct against the ground truth."
            )
            user_parts.append("Respond with a JSON object containing:")
            user_parts.append(
                '- "is_correct": boolean indicating whether the extraction result is correct'
            )
            user_parts.append(
                '- "error_reason": string or null, the reason if the extraction is incorrect'
            )
            user_parts.append(
                '- "patch_suggestion": object or null, suggested patch with keys '
                '"target_section", "operation", "content"'
            )
            user_content = "\n".join(user_parts)

        return [
            {"role": "system", "content": system_content},
            {"role": "user", "content": user_content},
        ]

    def _build_reflection_messages(
        self,
        analysis_prompt: StructuredPrompt,
        extraction_result: ExtractionResult,
        analysis_result: AnalysisResult,
        sample_spec: SampleSpec,
    ) -> list[dict[str, Any]]:
        """构建反思消息。"""
        system_content = self.renderer.render_system_message(analysis_prompt)

        parsed_output_text = (
            json.dumps(extraction_result.parsed_output, ensure_ascii=False)
            if extraction_result.parsed_output is not None
            else "null"
        )
        judgement_text = json.dumps(
            analysis_result.judgement, ensure_ascii=False
        )

        if self.analysis_reflection_template_path:
            user_content = render_prompt(
                self.analysis_reflection_template_path,
                sample_id=extraction_result.sample_id,
                raw_output=extraction_result.raw_output,
                parsed_output=parsed_output_text,
                status=extraction_result.status,
                judgement=judgement_text,
                analysis_correct=analysis_result.analysis_correct,
                error_reason=analysis_result.error_reason,
                sample_input=json.dumps(sample_spec.input, ensure_ascii=False, indent=2),
                ground_truth=json.dumps(sample_spec.ground_truth, ensure_ascii=False, indent=2),
            )
        else:
            user_parts: list[str] = []
            user_parts.append("# Extraction Result")
            user_parts.append(f"sample_id: {extraction_result.sample_id}")
            user_parts.append(f"raw_output: {extraction_result.raw_output}")
            user_parts.append(f"parsed_output: {parsed_output_text}")
            user_parts.append(f"status: {extraction_result.status}")
            user_parts.append("")
            user_parts.append("# Analysis Result (to reflect on)")
            user_parts.append(f"judgement: {judgement_text}")
            user_parts.append(f"analysis_correct: {analysis_result.analysis_correct}")
            user_parts.append(f"error_reason: {analysis_result.error_reason}")
            user_parts.append("")
            user_parts.append("# Sample Input")
            user_parts.append(json.dumps(sample_spec.input, ensure_ascii=False, indent=2))
            user_parts.append("")
            user_parts.append("# Ground Truth")
            user_parts.append(
                json.dumps(sample_spec.ground_truth, ensure_ascii=False, indent=2)
            )
            user_parts.append("")
            user_parts.append("# Task")
            user_parts.append(
                "The analysis above misjudged the extraction result. "
                "Reflect on why the analysis was wrong and how to fix the analysis prompt."
            )
            user_parts.append("Respond with a JSON object containing:")
            user_parts.append(
                '- "error_reason": why the analysis misjudged the extraction correctness'
            )
            user_parts.append(
                '- "patch_suggestion": suggested fix to the analysis prompt with keys '
                '"target_section", "operation", "content"'
            )
            user_parts.append('- "notes": list of additional observations')
            user_content = "\n".join(user_parts)

        return [
            {"role": "system", "content": system_content},
            {"role": "user", "content": user_content},
        ]

    def _parse_judgement(self, raw_output: str | None) -> dict[str, Any]:
        """解析模型输出为 judgement dict。

        尝试 JSON 解析：
        - 解析成功且为 dict，直接返回
        - 解析失败，尝试使用模型修复
        - 修复也失败，返回空 dict
        """
        if not raw_output:
            return {}

        # 首先尝试直接 JSON 解析
        try:
            parsed = json.loads(raw_output)
        except (json.JSONDecodeError, TypeError):
            parsed = None

        if parsed is not None and isinstance(parsed, dict):
            return parsed

        # 解析失败，尝试使用模型修复
        if self.model_client is not None:
            # analysis judgement 的预期 schema
            expected_schema = {
                "is_correct": bool,
                "error_reason": str | None,
                "patch_suggestion": dict | None,
            }
            repaired, repair_status = repair_json_output(
                raw_output=raw_output,
                expected_schema=expected_schema,
                model_client=self.model_client,
                model_config=self.model_config,
            )
            if repair_status == "repaired" and repaired is not None:
                return repaired

        return {}

    def _compute_actual_correct(
        self,
        extraction_result: ExtractionResult,
        ground_truth: dict[str, Any] | None,
    ) -> bool:
        """计算 ground truth 对 extraction result 的实际判断。"""
        parsed = extraction_result.parsed_output
        if not isinstance(parsed, dict) or not isinstance(ground_truth, dict):
            return False
        for field in self.primary_answer_fields:
            if field in parsed and field in ground_truth:
                pred = normalize_label(parsed.get(field), self.label_mapping)
                gt = normalize_label(ground_truth.get(field), self.label_mapping)
                return pred == gt
        return False

    def _extract_analysis_judgement(
        self, judgement: dict[str, Any]
    ) -> bool | None:
        """从 judgement 中提取 analysis 对 extraction result 是否正确的判断。"""
        if not isinstance(judgement, dict):
            return None
        if "is_correct" in judgement and isinstance(judgement["is_correct"], bool):
            return judgement["is_correct"]
        if "extraction_correct" in judgement and isinstance(
            judgement["extraction_correct"], bool
        ):
            return judgement["extraction_correct"]
        if "judgement" in judgement:
            value = judgement["judgement"]
            if isinstance(value, bool):
                return value
            if isinstance(value, str):
                lower = value.lower()
                if lower in ("correct", "true", "yes", "right"):
                    return True
                if lower in ("wrong", "false", "no", "incorrect", "error"):
                    return False
        return None

    def _extract_error_reason(
        self, judgement: dict[str, Any]
    ) -> str | None:
        """从 judgement 中提取错误原因。"""
        if not isinstance(judgement, dict):
            return None
        for key in ("error_reason", "reason", "explanation", "error"):
            value = judgement.get(key)
            if isinstance(value, str) and value:
                return value
        return None

    def _extract_patch_suggestion(
        self, judgement: dict[str, Any]
    ) -> dict[str, Any] | None:
        """从 judgement 中提取 patch_suggestion。"""
        if not isinstance(judgement, dict):
            return None
        suggestion = judgement.get("patch_suggestion")
        if isinstance(suggestion, dict) and suggestion:
            return suggestion
        return None

    def _extract_notes(self, judgement: dict[str, Any]) -> list[str]:
        """从 judgement 中提取 notes。"""
        if not isinstance(judgement, dict):
            return []
        value = judgement.get("notes")
        if isinstance(value, list):
            return [str(item) for item in value]
        if isinstance(value, str) and value:
            return [value]
        return []

    def _build_patch_suggestion(
        self,
        judgement: dict[str, Any],
        error_reason: str | None,
    ) -> dict[str, Any]:
        """生成 patch_suggestion。优先取 judgement 中的，否则基于 error_reason 构造。"""
        suggestion = self._extract_patch_suggestion(judgement)
        if suggestion is not None:
            return suggestion
        content = error_reason or "extraction result is incorrect"
        return {
            "target_section": "section_1",
            "operation": "replace",
            "content": content,
            "rationale": content,
        }


__all__ = ["AnalysisExecutor"]
